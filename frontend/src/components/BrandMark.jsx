/** Spotter mark: a cloud over a road running from a start point to a destination (weather + routing). */
export default function BrandMark({ size = 20 }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 11h7.5a3 3 0 0 0 .4-5.97A4.5 4.5 0 0 0 7.3 6.6 2.25 2.25 0 0 0 8 11Z" />
      <path d="M4 20.5c5 0 3.5-5 8.5-5H17" />
      <circle cx="4" cy="20.5" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="19.5" cy="15.5" r="2" />
    </svg>
  )
}
