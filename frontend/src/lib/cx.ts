/** Join the class names that are set. */
export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')
