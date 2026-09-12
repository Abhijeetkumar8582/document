import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import App from './App'
import Dashboard from './pages/Dashboard'
import Records from './pages/Records'
import RecordDetail from './pages/RecordDetail'
import Upload from './pages/Upload'
import AuditLog from './pages/AuditLog'
import BatchDetail from './pages/BatchDetail'
import Architecture from './pages/Architecture'
import { Empty } from './components/ui'
import './index.css'

function RouteError() {
  return (
    <div className="mx-auto max-w-xl px-4 py-16">
      <Empty title="Something went wrong on this page">
        Reload the page. If it keeps happening, the audit log and records are still reachable from the sidebar.
        <div className="mt-4">
          <a href="/" className="btn-primary">
            Back to the dashboard
          </a>
        </div>
      </Empty>
    </div>
  )
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'records', element: <Records /> },
      { path: 'records/:id', element: <RecordDetail /> },
      { path: 'upload', element: <Upload /> },
      { path: 'batches', element: <Navigate to="/upload" replace /> },
      { path: 'batches/:id', element: <BatchDetail /> },
      { path: 'audit', element: <AuditLog /> },
      { path: 'how-it-works', element: <Architecture /> },
      {
        path: '*',
        element: (
          <div className="mx-auto max-w-xl">
            <Empty title="Page not found">There is nothing at this address. Use the sidebar to get back.</Empty>
          </div>
        ),
      },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
