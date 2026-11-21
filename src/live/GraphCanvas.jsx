import { useEffect, useMemo, useState } from 'react'
import { getInitials } from './ProfileAvatar.jsx'

function GraphNodeAvatar({ photoUrl, label, isStudent, fill, stroke, textFill }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
  }, [photoUrl])

  const showImg = Boolean(photoUrl) && !failed

  return (
    <>
      <circle r="22" fill={fill} stroke={stroke} strokeWidth="1.8" />
      {showImg ? (
        <>
          <foreignObject x="-21" y="-21" width="42" height="42" style={{ pointerEvents: 'none' }}>
            <img
              src={photoUrl}
              alt=""
              referrerPolicy="no-referrer"
              className="profile-avatar-img"
              onError={() => setFailed(true)}
            />
          </foreignObject>
          <circle r="22" fill="none" stroke={stroke} strokeWidth="1.8" style={{ pointerEvents: 'none' }} />
        </>
      ) : (
        <text y="4" textAnchor="middle" fontSize="12" fontWeight="700" fill={textFill}>
          {isStudent ? 'Moi' : getInitials(label)}
        </text>
      )}
    </>
  )
}

function deriveFallbackGraph(solution, studentName) {
  const paths = []
  if (solution?.primary_path) paths.push(solution.primary_path)
  if (solution?.alternative_paths?.length) paths.push(...solution.alternative_paths)
  if (!paths.length) return { nodes: [], edges: [] }

  const nodesMap = new Map()
  const edgesMap = new Map()

  paths.forEach((path, pIdx) => {
    const isPrimary = pIdx === 0
    path.hops.forEach((hop, hIdx) => {
      if (!nodesMap.has(hop.from_id)) {
        nodesMap.set(hop.from_id, {
          id: hop.from_id,
          label: hIdx === 0 ? studentName || hop.from_name : hop.from_name,
          meta: hop.from_meta,
          kind: hIdx === 0 ? 'student' : 'hop',
        })
      }
      if (!nodesMap.has(hop.to_id)) {
        const isTarget = hop.to_id === solution.target.id
        nodesMap.set(hop.to_id, {
          id: hop.to_id,
          label: hop.to_name,
          meta: hop.to_meta,
          kind: isTarget ? 'target' : 'hop',
        })
      }
      const key = `${hop.from_id}->${hop.to_id}`
      if (!edgesMap.has(key)) {
        edgesMap.set(key, {
          id: key,
          source: hop.from_id,
          target: hop.to_id,
          edge_type: hop.edge_type,
          probability: hop.probability,
          reason: hop.reason,
          is_primary: isPrimary,
        })
      } else if (isPrimary) {
        edgesMap.get(key).is_primary = true
      }
    })
  })

  return {
    nodes: Array.from(nodesMap.values()),
    edges: Array.from(edgesMap.values()),
  }
}

export default function GraphCanvas({ graphData, solution, studentName, onSelectNode }) {
  const [selectedEdgeId, setSelectedEdgeId] = useState(null)

  const { nodes, edges } = useMemo(() => {
    if (graphData?.nodes?.length && graphData?.edges?.length) {
      return graphData
    }
    return deriveFallbackGraph(solution, studentName)
  }, [graphData, solution, studentName])

  const layout = useMemo(() => {
    if (!nodes.length) return null

    const studentNode = nodes.find((n) => n.kind === 'student') || nodes[0]
    const targetNode = nodes.find((n) => n.kind === 'target')

    // BFS from studentNode to compute column levels cleanly
    const adj = new Map()
    nodes.forEach((n) => adj.set(n.id, []))
    edges.forEach((e) => {
      adj.get(e.source)?.push(e.target)
      adj.get(e.target)?.push(e.source)
    })

    const depth = new Map([[studentNode.id, 0]])
    const queue = [studentNode.id]
    while (queue.length) {
      const cur = queue.shift()
      const d = depth.get(cur)
      for (const nxt of adj.get(cur) || []) {
        if (!depth.has(nxt)) {
          depth.set(nxt, d + 1)
          queue.push(nxt)
        }
      }
    }

    let maxCol = 0
    nodes.forEach((n) => {
      const col = depth.get(n.id) ?? 1
      if (col > maxCol) maxCol = col
    })
    if (targetNode) {
      depth.set(targetNode.id, Math.max(depth.get(targetNode.id) ?? maxCol, maxCol))
      maxCol = depth.get(targetNode.id)
    }

    const columns = new Map()
    nodes.forEach((n) => {
      const c = depth.get(n.id) ?? 1
      if (!columns.has(c)) columns.set(c, [])
      columns.get(c).push(n)
    })

    const width = Math.max(540, (maxCol + 1) * 165)
    const maxRows = Math.max(...Array.from(columns.values()).map((arr) => arr.length), 1)
    const height = Math.max(250, maxRows * 96 + 60)
    const padX = 82
    const stepX = maxCol > 0 ? (width - padX * 2) / maxCol : 0

    const pos = new Map()
    columns.forEach((colNodes, colIdx) => {
      const x = maxCol === 0 ? width / 2 : padX + colIdx * stepX
      const usableH = height - 64
      const stepY = usableH / (colNodes.length + 1)
      colNodes.forEach((n, rowIdx) => {
        pos.set(n.id, { x, y: 32 + (rowIdx + 1) * stepY })
      })
    })

    return { width, height, pos }
  }, [nodes, edges])

  if (!layout || !nodes.length) {
    return (
      <div className="app-empty-box">
        <p>Aucun chemin relationnel indirect disponible pour cette cible.</p>
      </div>
    )
  }

  const activeEdge =
    edges.find((e) => e.id === selectedEdgeId) || edges.find((e) => e.is_primary) || edges[0]

  return (
    <div className="app-graph-wrap">
      <svg
        className="app-graph-svg"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label="Graphe des chemins de mise en relation"
      >
        {edges.map((edge) => {
          const p1 = layout.pos.get(edge.source)
          const p2 = layout.pos.get(edge.target)
          if (!p1 || !p2) return null

          const dx = Math.abs(p2.x - p1.x) * 0.42
          const curveOffset = edge.is_primary ? 0 : 18
          const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y - curveOffset}, ${p2.x - dx} ${p2.y - curveOffset}, ${p2.x} ${p2.y}`
          const midX = (p1.x + p2.x) / 2
          const midY = (p1.y + p2.y) / 2 - curveOffset * 0.65
          const isSelected = activeEdge?.id === edge.id

          return (
            <g
              key={edge.id}
              className="app-graph-edge"
              onClick={() => setSelectedEdgeId(edge.id)}
              onMouseEnter={() => setSelectedEdgeId(edge.id)}
            >
              <path d={d} fill="none" stroke="transparent" strokeWidth="16" />
              <path
                d={d}
                fill="none"
                stroke={edge.is_primary ? 'var(--coral)' : isSelected ? 'var(--accent)' : 'var(--line)'}
                strokeWidth={edge.is_primary ? 2.6 : isSelected ? 2.2 : 1.6}
                strokeDasharray={edge.is_primary ? undefined : '5 4'}
              />
              <rect
                x={midX - 20}
                y={midY - 11}
                width="40"
                height="20"
                rx="10"
                fill={edge.is_primary ? 'var(--coral-soft)' : 'var(--surface)'}
                stroke={edge.is_primary ? 'var(--coral)' : 'var(--line)'}
                strokeWidth="1"
              />
              <text
                x={midX}
                y={midY + 3}
                textAnchor="middle"
                fontSize="10.5"
                fontWeight="700"
                fill={edge.is_primary ? 'var(--coral-ink)' : 'var(--muted)'}
              >
                {Math.round(edge.probability * 100)}%
              </text>
            </g>
          )
        })}

        {nodes.map((node) => {
          const p = layout.pos.get(node.id)
          if (!p) return null
          const isStudent = node.kind === 'student'
          const isTarget = node.kind === 'target'
          const fill = isStudent ? 'var(--accent)' : isTarget ? 'var(--sun)' : 'var(--surface)'
          const stroke = isStudent ? 'var(--accent)' : isTarget ? 'var(--text)' : 'var(--line)'
          const textFill = isStudent ? '#ffffff' : 'var(--text)'

          return (
            <g
              key={node.id}
              className="app-graph-node"
              transform={`translate(${p.x}, ${p.y})`}
              onClick={() => onSelectNode?.(node.id)}
              role="button"
              tabIndex={0}
              aria-label={`Voir le profil de ${node.label}`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onSelectNode?.(node.id)
                }
              }}
            >
              <GraphNodeAvatar
                photoUrl={node.photo_url}
                label={node.label}
                isStudent={isStudent}
                fill={fill}
                stroke={stroke}
                textFill={textFill}
              />
              <text y="37" textAnchor="middle" fontSize="11.5" fontWeight="650" fill="var(--text)">
                {node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label}
              </text>
              {node.meta && (
                <text y="51" textAnchor="middle" fontSize="9.8" fill="var(--muted)">
                  {node.meta.length > 22 ? `${node.meta.slice(0, 21)}…` : node.meta}
                </text>
              )}
            </g>
          )
        })}
      </svg>

      {activeEdge && (
        <div className="app-graph-legend">
          <span className="app-badge neutral">
            {activeEdge.edge_type === 'EXPLICIT_LINKEDIN' ? 'Lien LinkedIn' : activeEdge.edge_type.replace('INFERRED_', 'Lien ')} · {Math.round(activeEdge.probability * 100)}%
          </span>
          <span>{activeEdge.reason}</span>
          <span className="muted small">Cliquez sur un nœud pour ouvrir sa fiche.</span>
        </div>
      )}
    </div>
  )
}
