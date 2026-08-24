import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  message: string
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || 'حدث خطأ غير متوقع' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI error boundary caught:', error, info.componentStack)
  }

  handleReload = () => {
    this.setState({ hasError: false, message: '' })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app-error-boundary" role="alert" dir="rtl">
          <div className="app-error-boundary__card">
            <h2>حدث خطأ في الواجهة</h2>
            <p>حدث خطأ غير متوقع في هذه الصفحة. أعد المحاولة أو ارجع إلى الصفحة السابقة.</p>
            <button className="app-error-boundary__btn" onClick={this.handleReload}>
              إعادة تحميل الصفحة
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
