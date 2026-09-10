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
import './index.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'records', element: <Records /> },
      { path: 'records/:id', element: <RecordDetail /> },
      { path: 'upload', element: <Upload /> },
      { path: 'batches', element: <Navigate to="/upload" replace /> },
      { path: 'batches/:id', element: <BatchDetail /> },
      { path: 'audit', element: <AuditLog /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
