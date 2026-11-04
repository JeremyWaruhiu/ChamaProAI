// The same rule as db.normalise_phone. The API has the last word; this is what
// lets the sign-up form say so before anything is sent.

const MOBILE = /^(?:\+?254|0)([17][0-9]{8})$/

/** A Kenyan mobile number as +254XXXXXXXXX, or null if it is not one. */
export function normalisePhone(typed: string): string | null {
  const match = MOBILE.exec(typed.replace(/[\s()-]/g, ''))
  return match ? `+254${match[1]}` : null
}
