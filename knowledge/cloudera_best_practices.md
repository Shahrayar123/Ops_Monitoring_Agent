# Cloudera Ops — Generic Remediation Best Practices

This file is the **fallback knowledge base** the AI analyst consults when the Ops
team's own runbook or known-issues file does not cover a breach. It is retrieved
as context (never hard-coded into the model prompt), so it can be edited freely
without touching code. When `runbook.md` or `known_issues.md` are present in this
folder, those take precedence — this file fills the gaps.

Each section below is keyed to one of the nine monitoring checks. Keep headings
stable (the retriever matches on the `check:` tag) but edit the guidance freely.

---

## check: host_health
**Signal:** Cloudera Manager reports a host's `healthSummary` as CONCERNING or BAD.

**Investigate**
- Open CM → Hosts → the affected host → Health Tests to see which specific test failed (clock offset, swapping, disk, agent status).
- Check the Cloudera Manager Agent is running: `systemctl status cloudera-scm-agent`.
- Review the host's `/var/log/cloudera-scm-agent/cloudera-scm-agent.log` for recent errors.

**Common causes & fixes**
- **Agent down / not heartbeating:** restart the agent (`systemctl restart cloudera-scm-agent`).
- **Clock offset (NTP):** ensure `chronyd`/`ntpd` is running and synced; large offsets fail health tests and break Kerberos.
- **Swapping / memory pressure:** identify the memory hog; lower service heap or add memory.
- **Full root or log disk:** see the disk guidance below.

**Escalate if:** the host is a master/edge node (NameNode, ResourceManager, CM), or `healthSummary` is BAD rather than CONCERNING.

---

## check: heartbeat
**Signal:** A host has not heartbeated to Cloudera Manager within the configured window.

**Investigate**
- A silent host is usually down, network-partitioned, or its CM agent has stopped.
- Ping the host and check SSH reachability from the CM server.
- Check `cloudera-scm-agent` status and the agent log on the host.

**Common causes & fixes**
- **Agent stopped/crashed:** restart it; enable it on boot.
- **Network partition:** verify the host's route to the CM server on the agent port (7182).
- **Host powered off / hung:** confirm with the hardware/hypervisor console before assuming a software fault.

**Impact note:** a silent host also stops reporting metrics, so CPU/RAM/disk/network for that host will look stale, and any roles it hosts (DataNode, NodeManager) drop out of their services.

---

## check: cpu_percent
**Signal:** A host's CPU utilisation is above the configured threshold.

**Investigate**
- Identify the top processes: `top`, `htop`, or `ps aux --sort=-%cpu | head`.
- Correlate with YARN/Impala/Spark workloads — a heavy query or job is the usual cause.

**Common causes & fixes**
- **Legitimate heavy workload:** confirm against the YARN scheduler / Impala queries; consider queue limits or off-peak scheduling.
- **Runaway or stuck process:** isolate and restart the offending role.
- **Under-provisioned host:** if sustained, rebalance roles or add capacity.

**Note:** brief CPU spikes are normal on data nodes during jobs; sustained saturation across many nodes is the real concern.

---

## check: ram_percent
**Signal:** A host's memory utilisation is above the configured threshold.

**Investigate**
- `free -h` and `ps aux --sort=-%mem | head`; check for swapping (`si`/`so` in `vmstat`).
- Review service heap sizes in CM (DataNode, NodeManager, Impala daemon, RegionServer).

**Common causes & fixes**
- **Oversubscribed heaps:** total configured heaps exceed physical RAM; reduce or rebalance.
- **Impala / Spark memory-heavy queries:** enforce per-query memory limits and admission control.
- **Memory leak in a role:** restart the role; capture a heap dump if recurring.

**Escalate if:** the host is actively swapping — that degrades every service on it and can cascade to heartbeat failures.

---

## check: disk_percent
**Signal:** A watched mount (data disk `/u01`–`/uNN` or an OS mount) is above the fullness threshold, or an oversized log file was found.

**Investigate**
- On the host: `df -h` for the mount, then `du -xh --max-depth=1 <mount> | sort -h | tail` to find the biggest consumers.
- For log growth, check `/var/log/<service>` and CM role log directories.

**Common causes & fixes**
- **HDFS data disks (`/uNN`) filling:** this is capacity pressure — run HDFS balancer, expire snapshots/trash (`hdfs dfs -expunge`), delete or archive cold data, or add DataNode capacity. Do **not** manually delete files under the DataNode data dirs.
- **`/var` full from logs:** rotate/compress logs, lower log retention or verbosity, clear old CM/agent logs.
- **`/tmp` full:** clear stale scratch (respecting running jobs); check Impala/Spark scratch dirs.
- **A single runaway log file:** identify the noisy component and fix the underlying error causing the log spam.

**Predictive note:** if a data disk is filling at a steady rate, estimate time-to-full from the fill rate and act before it reaches 100% — a full DataNode disk takes that volume offline and can trigger under-replication.

---

## check: hdfs_health
**Signal:** HDFS `healthSummary` is CONCERNING/BAD, or stored data grew unusually fast over the window.

**Investigate**
- CM → HDFS → Health Tests; run `hdfs dfsadmin -report` for capacity, under-replicated/corrupt/missing blocks.
- `hdfs fsck / -files -blocks` (carefully, can be heavy) to locate corrupt/missing blocks.

**Common causes & fixes**
- **Under-replicated blocks:** usually self-heals after a DataNode returns; if persistent, check DataNode health and network.
- **Missing/corrupt blocks:** identify affected files; restore from backup/snapshot if data is lost.
- **Capacity near full / fast growth:** run the balancer, clear trash/snapshots, add capacity; investigate the write job driving abnormal growth.
- **NameNode issues (safe mode, checkpointing):** confirm NameNode + JournalNodes healthy; leave safe mode only after verifying block reports.

**Escalate if:** blocks are missing (potential data loss) or the NameNode is unhealthy — HDFS is the storage foundation for the whole cluster.

---

## check: service_status
**Signal:** A service is not running, or a service/role health check is CONCERNING/BAD (worst-of the CM rollup and the individual checks).

**Investigate**
- CM → the service → Instances/Health Tests to find the exact failing role and check.
- Read the role's recent log (CM → role → Log Files) around the time it went unhealthy.

**Common causes & fixes**
- **A role is down:** restart it from CM; if it won't start, the role log states why (port conflict, config error, dependency down).
- **Dependency cascade:** a service often looks unhealthy because a service it depends on is down (e.g. YARN/HBase suffer when HDFS is unhealthy) — fix the root service first.
- **Config staleness:** if CM shows stale config, deploy client config / restart the affected roles.

**Order of operations:** fix foundational services first (ZooKeeper → HDFS → YARN → everything else), then re-check the dependents.

---

## check: alerts
**Signal:** Active CRITICAL or IMPORTANT alerts exist in Cloudera Manager.

**Investigate**
- CM → Diagnostics → Events (filter alert==true) to read each alert's summary and source role.
- Group related alerts — many alerts often share one root cause (a down host or service).

**Common causes & fixes**
- **Event Server store full / mgmt service unhealthy:** the CM management services (Event Server, Service Monitor, Host Monitor) have their own storage — purge or expand it, then restart the mgmt roles.
- **Role health alerts:** each maps to a service/role issue — resolve via the relevant section above.
- **Alert storm from one host:** silence at the source by fixing the host, not by muting alerts.

**Triage rule:** number and severity matter — many CRITICALs (tens) signal a systemic problem, not isolated noise.

---

## check: network
**Signal:** A host shows (near) zero receive throughput, elevated frame errors, or is unreachable by ping.

**Investigate**
- Confirm the host is actually up (correlate with heartbeat).
- On the host: `ip -s link` for interface errors/drops; `ethtool <iface>` for link state.

**Common causes & fixes**
- **Dead interface / cable / switch port:** check link state and physical connectivity; fail over to a bonded interface if configured.
- **Frame errors climbing:** often a bad NIC, cable, or duplex mismatch — replace/re-seat and check switch counters.
- **Host unreachable:** treat as a down/partitioned host (see heartbeat).

**Impact note:** network loss on a DataNode causes replication traffic to reroute and can trigger under-replication and slow jobs.

---

## general: cross-service dependencies
When several checks breach at once, look for a single root cause before treating them as separate incidents:
- A **down or unhealthy host** degrades its heartbeat, network, and every role it hosts.
- **Unhealthy HDFS** degrades YARN, HBase, Impala, and Hive that depend on it.
- **A full data disk** can take a DataNode offline, causing HDFS under-replication and service alerts.
Fix the foundational cause first, then re-run the checks to confirm the dependents recover.

## general: safety
- Never delete files directly under HDFS DataNode data directories or NameNode metadata dirs.
- Prefer CM-driven restarts over manual `kill`; CM restarts respect dependencies and config.
- On any destructive step (clearing data, restarting a master role), confirm impact and, where possible, do it during a maintenance window.
