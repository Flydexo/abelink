export default function StepIllustration({ step }) {
  return (
    <svg className="step-illustration" viewBox="0 0 320 190" fill="none" aria-hidden="true" focusable="false">
      <circle cx="160" cy="96" r="78" fill="var(--accent-soft)" />
      {step === 0 && <>
        <rect x="40" y="34" width="225" height="106" rx="18" fill="var(--surface)" stroke="var(--line)" />
        <path d="M66 62h118M66 77h167M66 92h94" stroke="var(--line)" strokeWidth="6" strokeLinecap="round" />
        <rect x="65" y="108" width="64" height="19" rx="9.5" fill="var(--sun-soft)" />
        <text x="78" y="121" fill="var(--accent)" fontSize="10" fontWeight="600">Énergie</text>
        <rect x="136" y="108" width="66" height="19" rx="9.5" fill="var(--accent-soft)" />
        <text x="146" y="121" fill="var(--accent)" fontSize="10" fontWeight="600">Césure</text>
        <rect x="204" y="121" width="77" height="43" rx="16" fill="var(--accent)" />
        <path d="M235 143h17m-6-6 6 6-6 6" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="m270 40 5-10m4 17 10-2" stroke="var(--coral)" strokeWidth="3" strokeLinecap="round" />
      </>}
      {step === 1 && <>
        <path d="m66 98 88-42 103 39-97 55-94-52Zm88-42 6 94m-94-52 191-3" stroke="var(--accent)" strokeOpacity=".25" strokeWidth="1.5" strokeDasharray="4 5" />
        <path d="m66 98 94 52 97-55" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" />
        {[[66, 98], [154, 56], [257, 95], [160, 150]].map(([centerX, centerY], index) => <g key={index}>
          <circle cx={centerX} cy={centerY} r="22" fill={index === 3 ? 'var(--accent)' : 'var(--surface)'} stroke={index === 3 ? 'var(--accent)' : 'var(--line)'} />
          <circle cx={centerX} cy={centerY - 5} r="5" fill={index === 3 ? 'white' : 'var(--accent)'} />
          <path d={
            'M' + (centerX - 9) + ' ' + (centerY + 10) + 'q0-12 9-12t9 12'
          } fill={index === 3 ? 'white' : 'var(--accent)'} />
        </g>)}
        <circle cx="235" cy="42" r="17" fill="var(--sun)" /><path d="m229 42 4 4 8-9" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </>}
      {step === 2 && <>
        <rect x="60" y="25" width="199" height="142" rx="14" fill="var(--surface)" stroke="var(--line)" transform="rotate(-4 160 96)" />
        <path d="M87 59h96" stroke="var(--accent)" strokeWidth="5" strokeLinecap="round" />
        {[83, 108, 133].map((position, index) => <g key={position}>
          <circle cx="88" cy={position} r="7" fill="var(--accent-soft)" />
          <path d={'m85 ' + position + ' 2 2 4-4'} stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
          <path d={'M106 ' + position + 'h' + (index === 2 ? 67 : 109)} stroke="var(--line)" strokeWidth="5" strokeLinecap="round" />
        </g>)}
        <circle cx="250" cy="139" r="29" fill="var(--coral)" />
        <path d="m236 137 28-10-10 27-5-12-13-5Zm13 5 15-15" stroke="white" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </>}
    </svg>
  )
}
