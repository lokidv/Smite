import { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="min-h-[200px] p-6 rounded-2xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-center flex flex-col items-center justify-center m-4">
          <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/60 flex items-center justify-center text-red-600 dark:text-red-300 text-xl font-bold mb-3">
            ⚠️
          </div>
          <h3 className="text-lg font-bold text-red-900 dark:text-red-200 mb-1">
            خطایی در پردازش این بخش رخ داده است
          </h3>
          <p className="text-xs font-mono text-red-700 dark:text-red-300 bg-red-100/70 dark:bg-red-900/40 p-2.5 rounded-lg max-w-xl break-all my-3">
            {this.state.error?.message || 'Unknown runtime error'}
          </p>
          <button
            type="button"
            onClick={() => {
              this.setState({ hasError: false, error: null })
              window.location.reload()
            }}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-bold rounded-lg shadow transition cursor-pointer"
          >
            بارگذاری مجدد (Reload)
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
