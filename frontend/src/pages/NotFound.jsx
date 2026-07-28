import { Link } from 'react-router-dom'
import { Button } from '../components/ui'

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center p-6">
      <div className="text-center">
        <div className="text-7xl font-black text-brand-600">404</div>
        <p className="mt-2 text-lg font-semibold" style={{ color: 'var(--ink)' }}>
          Page not found
        </p>
        <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
          The page you're looking for doesn't exist.
        </p>
        <Link to="/dashboard">
          <Button className="mt-6">Back to dashboard</Button>
        </Link>
      </div>
    </div>
  )
}
