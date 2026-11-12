import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

/** Accessible dialog: closes on Esc, backdrop click or the X; focuses the first field when opened. */
export default function Modal({ title, icon: Icon, onClose, children }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    // Focus the first text field (not the preset chips above it), else the first button
    const dialog = dialogRef.current
    ;(dialog?.querySelector('input[type="text"], input:not([type])') || dialog?.querySelector('button:not(.modal-close)'))?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={dialogRef}>
        <div className="modal-header">
          <h2 id="modal-title">{Icon && <Icon size={18} />} {title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
