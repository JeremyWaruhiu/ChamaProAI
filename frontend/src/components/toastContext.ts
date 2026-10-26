import { createContext, useContext } from 'react'

export type ToastTone = 'success' | 'error' | 'info'
export const ToastContext = createContext<(text: string, tone?: ToastTone) => void>(() => {})

/** Show a short confirmation ("Guarantor verified"). Errors stay longer. */
export function useToast() {
  return useContext(ToastContext)
}
