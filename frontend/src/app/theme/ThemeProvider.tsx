import {
  createContext,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useState,
} from 'react'

export type AdminTheme = 'light' | 'dark'

const STORAGE_KEY = 'qentry.admin.theme'

type ThemeContextValue = {
  theme: AdminTheme
  setTheme: (theme: AdminTheme) => void
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readInitialTheme(): AdminTheme {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

function applyTheme(theme: AdminTheme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

/**
 * The single source of truth for the administration console appearance.
 * Theme tokens are applied to the document root, so every workspace page and
 * modal receives the same mode without page-level theme state.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AdminTheme>(readInitialTheme)

  useLayoutEffect(() => {
    applyTheme(theme)
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Private browsing may deny storage; the current session still works.
    }
  }, [theme])

  const setTheme = (nextTheme: AdminTheme) => setThemeState(nextTheme)
  const toggleTheme = () => setThemeState(current => current === 'dark' ? 'light' : 'dark')

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useAdminTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useAdminTheme must be used inside ThemeProvider')
  return context
}
