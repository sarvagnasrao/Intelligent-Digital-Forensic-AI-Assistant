  import React, { useState, useEffect, useRef, useCallback } from 'react'
  import { useParams, useNavigate } from 'react-router-dom'
  import ForceGraph2D from 'react-force-graph-2d'
  import { Search, RefreshCw, ZoomIn, ZoomOut, Maximize2, Download, X, ExternalLink, Users, MapPin, Building2, Wifi, FileText, Link, Filter, Info } from 'lucide-react'
  import { getGraphData, getEntities } from '../api/client'
  import toast from 'react-hot-toast'

  // ── Canvas palette ──────────────────────────────────────────
  //
  // A 2D canvas cannot resolve `var(--x)`. Per the HTML spec, assigning an
  // unparseable value to fillStyle/strokeStyle is a silent no-op: the
  // previous value survives. That made every `var(...)` in this file's draw
  // callbacks a no-op, which had three separate visible consequences:
  //
  //   1. Node labels were drawn with the *node's own* fill colour, because
  //      the only assignment that ever took effect on that context was the
  //      circle fill a few lines earlier.
  //   2. Where a background pill was drawn, the pill fill was valid and dark
  //      (`rgba(4,5,11,0.75)`), and the text colour that followed it was
  //      rejected - so the text stayed dark. Dark text on a dark pill:
  //      the labels were drawn and were completely invisible.
  //   3. Dimming had no effect at all. A non-highlighted edge asked for
  //      `var(--color-white-06)` and inherited whatever the previously
  //      drawn edge happened to be, so de-emphasising the graph by
  //      highlighting a node did nothing to the edges.
  //
  // None of these raise an error, which is why it survived review: the code
  // reads as though it themes correctly. It is the same defect class as
  // everything else in this app - a true-shaped line of code that does not
  // do what it says - one layer down in the renderer.
  //
  // So the variables are resolved for real, from the computed style, and
  // re-read when the theme class on <html> changes. The theme is applied as
  // a `light`/`dark` class rather than through ThemeContext, and `system`
  // mode can flip it on an OS event, so a MutationObserver is both simpler
  // and more reliable than threading the context value through here.
  //
  // Each entry has a concrete fallback. A missing variable must not resolve
  // to `transparent`, which would be the same no-op in a slower form: the
  // fallback is a colour that is legible against the pill, not a colour
  // that merely parses.
  const CANVAS_COLORS = {
    text: {
      varName: '--text-primary',
      fallback: '#e2e4f0',
    },
    textDim: {
      varName: '--color-white-4',
      fallback: 'rgba(226, 228, 240, 0.4)',
    },
    selectedBorder: {
      varName: '--color-white-full',
      fallback: '#ffffff',
    },
    dimEdge: {
      varName: '--color-white-06',
      fallback: 'rgba(255, 255, 255, 0.06)',
    },
  }

  function readCanvasPalette() {
    const out = {}
    let cs = null
    try {
      cs = getComputedStyle(document.documentElement)
    } catch {
      // No DOM (or a stubbed one in a test). The fallbacks below stand in.
    }
    for (const [key, spec] of Object.entries(CANVAS_COLORS)) {
      let value = ''
      if (cs) {
        try {
          value = (cs.getPropertyValue(spec.varName) || '').trim()
        } catch {
          value = ''
        }
      }
      // A custom property that resolves to something the canvas cannot
      // parse - a nested var(), an empty value, a calc() - is treated the
      // same as an absent one, because the outcome is identical: the
      // assignment is dropped and the previous colour survives.
      out[key] = CANVAS_IS_USABLE_COLOR(value) ? value : spec.fallback
    }
    return out
  }

  function CANVAS_IS_USABLE_COLOR(value) {
    if (!value) return false
    // Deliberately narrow. Anything outside this set is a value a canvas
    // 2D context would reject, and rejecting it is the failure mode this
    // whole function exists to prevent.
    return /^(#|rgba?\(|hsla?\()/i.test(value)
  }

  function useCanvasPalette() {
    const [palette, setPalette] = useState(() => readCanvasPalette())
    useEffect(() => {
      const refresh = () => setPalette(readCanvasPalette())
      const root = document.documentElement
      const observer = new MutationObserver(refresh)
      observer.observe(root, {
        attributes: true,
        attributeFilter: ['class', 'style'],
      })
      return () => observer.disconnect()
    }, [])
    return palette
  }

  // Node type config
  const NODE_TYPES = {
    Person: {
      color: '#f87171',
      icon: '👤',
      size: 8,
    },
    Location: {
      color: '#34d399',
      icon: '📍',
      size: 7,
    },
    Organization: {
      color: '#fbbf24',
      icon: '🏢',
      size: 7,
    },
    IP: {
      color: '#a78bfa',
      icon: '🌐',
      size: 6,
    },
    File: {
      color: '#4ade80',
      icon: '📄',
      size: 5,
    },
    Device: {
      color: '#67e8f9',
      icon: '💻',
      size: 6,
    },
  }

  const DEFAULT_COLOR = '#94a3b8'

  function getNodeColor(node) {
    return NODE_TYPES[node.type]?.color || DEFAULT_COLOR
  }

  function getNodeSize(node) {
    const base = NODE_TYPES[node.type]?.size || 6
    const freq = node.frequency || 1
    return base + Math.min(Math.log2(freq + 1) * 2, 8)
  }

  // Node Inspector panel
  function NodeInspector({ node, caseId, onClose, navigate, position }) {
    if (!node) return null
    const cfg = NODE_TYPES[node.type] || {}

    const style = {
      position: 'absolute',
      width: 280,
      background: 'rgba(14,15,26,0.95)',
      backdropFilter: 'blur(20px)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 16,
      zIndex: 20,
      overflow: 'hidden',
      boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
    }

    if (position) {
      style.left = Math.max(16, Math.min(position.x - 140, window.innerWidth - 300))
      style.top = position.y + 20
    } else {
      style.top = 16
      style.right = 16
    }

    return (
      <div style={style}>
        {/* Header */}
        <div style={{
          padding: '14px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.07)',
          background: `${cfg.color || DEFAULT_COLOR}10`,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 10,
        }}>
          <div style={{
            width: 36, height: 36,
            borderRadius: 10,
            background: `${cfg.color || DEFAULT_COLOR}20`,
            border: `1px solid ${cfg.color || DEFAULT_COLOR}40`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18, flexShrink: 0,
          }}>
            {cfg.icon || '•'}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{
              fontSize: 14, fontWeight: 600,
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {node.label}
            </p>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8, marginTop: 3,
            }}>
              <span style={{
                fontSize: 10,
                fontWeight: 500,
                padding: '1px 7px',
                borderRadius: 4,
                background: `${cfg.color || DEFAULT_COLOR}18`,
                border: `1px solid ${cfg.color || DEFAULT_COLOR}30`,
                color: cfg.color || DEFAULT_COLOR,
              }}>
                {node.type}
              </span>
              <span style={{
                fontSize: 10,
                color: 'var(--color-white-3)',
              }}>
                {node.frequency || 1} mention(s)
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              padding: 4, borderRadius: 6,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--color-white-3)',
              display: 'flex',
              flexShrink: 0,
            }}>
            <X size={14} />
          </button>
        </div>

        {/* Connections */}
        {node.connections?.length > 0 && (
          <div style={{ padding: '12px 16px' }}>
            <p style={{
              fontSize: 10, fontWeight: 600,
              color: 'var(--color-white-3)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 8,
            }}>
              Connected to ({node.connections.length})
            </p>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              maxHeight: 200,
              overflowY: 'auto',
            }}>
              {node.connections
                .slice(0, 15)
                .map((conn, i) => {
                const connCfg = NODE_TYPES[conn.type] || {}
                return (
                  <div key={i} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '5px 8px',
                    borderRadius: 6,
                    background: 'var(--color-white-03)',
                  }}>
                    <span style={{
                      width: 8, height: 8,
                      borderRadius: '50%',
                      background: connCfg.color || DEFAULT_COLOR,
                      flexShrink: 0,
                    }} />
                    <span style={{
                      fontSize: 11,
                      color: 'var(--color-white-6)',
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {conn.label}
                    </span>
                    {conn.rel && (
                      <span style={{
                        fontSize: 9,
                        color: 'var(--color-white-2)',
                        fontFamily: 'monospace',
                        flexShrink: 0,
                      }}>
                        {conn.rel}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', gap: 8,
        }}>
          {node.type === 'Person' && (
            <button
              onClick={() => {
                navigate(`/cases/${caseId}/profiles?name=${encodeURIComponent(node.label)}&type=${encodeURIComponent(node.type)}`)
                onClose()
              }}
              style={{
                flex: 1,
                padding: '7px',
                borderRadius: 8,
                background: 'rgba(99,102,241,0.15)',
                border: '1px solid rgba(99,102,241,0.3)',
                color: '#818cf8',
                fontSize: 11, fontWeight: 500,
                cursor: 'pointer',
              }}>
              Generate Profile
            </button>
          )}
          <button
            onClick={() => {
              navigate(`/cases/${caseId}/profiles?name=${encodeURIComponent(node.label)}&type=${encodeURIComponent(node.type)}`)
              onClose()
            }}
            style={{
              flex: 1,
              padding: '7px',
              borderRadius: 8,
              background: 'var(--color-white-05)',
              border: '1px solid rgba(255,255,255,0.09)',
              color: 'var(--color-white-5)',
              fontSize: 11,
              cursor: 'pointer',
            }}>
            Investigate
          </button>
        </div>
      </div>
    )
  }

  export default function EntityMapPage() {
    const { caseId } = useParams()
    const navigate = useNavigate()
    const graphRef = useRef()
    const [graphData, setGraphData] = useState({ nodes: [], links: [] })
    const [filteredData, setFilteredData] = useState({ nodes: [], links: [] })
    const [loading, setLoading] = useState(true)
    // Resolved from the stylesheet, because a canvas 2D context cannot
    // read var() itself - see CANVAS_COLORS above for what that silently
    // cost this page before.
    const palette = useCanvasPalette()
    const [search, setSearch] = useState('')
    const [selectedTypes, setSelectedTypes] = useState([])
    const [selectedNode, setSelectedNode] = useState(null)
    const [popupPos, setPopupPos] = useState({ x: 0, y: 0 })
    const [counts, setCounts] = useState({})
    const [highlightNodes, setHighlightNodes] = useState(new Set())
    const [highlightLinks, setHighlightLinks] = useState(new Set())
    const [hoverNode, setHoverNode] = useState(null)

    useEffect(() => {
      loadGraph()
    }, [caseId])

    useEffect(() => {
      applyFilters()
    }, [graphData, search, selectedTypes])

    useEffect(() => {
      if (!graphRef.current) return
      // Stronger repulsion to spread nodes
      graphRef.current.d3Force('charge')?.strength(-300)
      graphRef.current.d3Force('link')?.distance(80)?.strength(0.3)
      graphRef.current.d3Force('collision')?.radius(20)
    }, [graphRef.current, filteredData.nodes.length])

    const loadGraph = async () => {
      setLoading(true)
      try {
        const res = await getGraphData(caseId)
        const data = res.data

        const graph = data.graph || { nodes: [], edges: [] }

        // Build connection info for each node
        const connectionMap = {}
        ;(graph.edges || []).forEach(edge => {
          const src = edge.source
          const tgt = edge.target
          if (!connectionMap[src]) connectionMap[src] = []
          if (!connectionMap[tgt]) connectionMap[tgt] = []
          connectionMap[src].push({
            label: tgt,
            rel: edge.relation_type || edge.relationship || edge.type || ''
          })
          connectionMap[tgt].push({
            label: src,
            rel: edge.relation_type || edge.relationship || edge.type || ''
          })
        })

        const nodes = (graph.nodes || [])
          .map(n => ({
            id: n.id || n.name,
            label: n.name || n.label || n.id,
            type: n.type || n.entity_type || 'Unknown',
            frequency: n.frequency || 1,
            is_flagged: n.is_flagged,
            connections: connectionMap[n.id || n.name] || [],
          }))

        const links = (graph.edges || [])
          .map(e => ({
            source: e.source,
            target: e.target,
            type: e.relation_type || e.relationship || e.type || 'CO_MENTIONED',
          }))

        // Count by type
        const typeCounts = {}
        nodes.forEach(n => {
          typeCounts[n.type] = (typeCounts[n.type] || 0) + 1
        })
        setCounts(typeCounts)
        setGraphData({ nodes, links })
      } catch {
        toast.error('Failed to load graph')
      } finally {
        setLoading(false)
      }
    }

    const applyFilters = () => {
      let nodes = graphData.nodes

      if (selectedTypes.length > 0) {
        nodes = nodes.filter(n => selectedTypes.includes(n.type))
      }

      if (search) {
        const q = search.toLowerCase()
        const matchedIds = new Set(
          nodes.filter(n => n.label.toLowerCase().includes(q)).map(n => n.id)
        )
        nodes = nodes.filter(n => matchedIds.has(n.id))
      }

      const nodeIds = new Set(nodes.map(n => n.id))
      const links = graphData.links.filter(
        l => nodeIds.has(typeof l.source === 'object' ? l.source.id : l.source) &&
             nodeIds.has(typeof l.target === 'object' ? l.target.id : l.target)
      )

      setFilteredData({ nodes, links })
    }

    const toggleType = (type) => {
      setSelectedTypes(prev =>
        prev.includes(type)
          ? prev.filter(t => t !== type)
          : [...prev, type]
      )
    }

    // Highlight on hover
    const handleNodeHover = useCallback(
      node => {
        const hl = new Set()
        const hlLinks = new Set()
        if (node) {
          hl.add(node)
          filteredData.links.forEach(l => {
            const src = typeof l.source === 'object' ? l.source.id : l.source
            const tgt = typeof l.target === 'object' ? l.target.id : l.target
            if (src === node.id || tgt === node.id) {
              hlLinks.add(l)
              filteredData.nodes.forEach(n => {
                if (n.id === src || n.id === tgt) {
                  hl.add(n)
                }
              })
            }
          })
        }
        setHighlightNodes(hl)
        setHighlightLinks(hlLinks)
        setHoverNode(node || null)
      }, [filteredData]
    )

    const handleNodeClick = useCallback(
      node => {
        setSelectedNode(prev => prev?.id === node.id ? null : node)
        if (graphRef.current) {
          const { x, y } = graphRef.current.graph2ScreenCoords(node.x, node.y)
          setPopupPos({ x, y })
        }
      }, []
    )

    // Draw node with label
    const nodeCanvasObject = useCallback(
      (node, ctx, globalScale) => {
        const r = getNodeSize(node)
        const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node)
        const isSelected = selectedNode?.id === node.id
        const color = getNodeColor(node)

        // Glow for flagged or selected
        if (isSelected || node.is_flagged) {
          ctx.beginPath()
          ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI)
          ctx.fillStyle = isSelected ? `${color}40` : 'rgba(245,158,11,0.3)'
          ctx.fill()
        }

        // Node circle
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
        ctx.fillStyle = isHighlighted ? color : `${color}50`
        ctx.fill()

        // Border
        ctx.strokeStyle = isSelected ? palette.selectedBorder : isHighlighted ? `${color}cc` : `${color}30`
        ctx.lineWidth = isSelected ? 2 : isHighlighted ? 1.5 : 0.5
        ctx.stroke()

        // Label — only show at sufficient zoom
        if (globalScale >= 0.6) {
          const label = node.label
          const fontSize = Math.max(10 / globalScale, isHighlighted ? 3 : 2.5)
          ctx.font = `${isHighlighted ? 500 : 400} ${fontSize}px Inter,sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillStyle = isHighlighted ? palette.text : palette.textDim

          // Background pill for readability
          if (isHighlighted || isSelected) {
            const tw = ctx.measureText(label).width
            ctx.fillStyle = 'rgba(4,5,11,0.75)'
            ctx.beginPath()
            const padding = fontSize * 0.4
            ctx.roundRect(
              node.x - tw/2 - padding,
              node.y + r + 2,
              tw + padding * 2,
              fontSize + padding,
              3)
            ctx.fill()
            // Restored to a real colour, not `var(--text-primary)`. The
            // pill above is unconditionally dark; in light mode a light
            // `--text-primary` on it would be just as unreadable as the
            // invisible text this replaces. The pill is the thing that
            // guarantees contrast, so the text inside it is pinned to a
            // colour that reads against that pill in either theme.
            ctx.fillStyle = '#e2e4f0'
          }

          ctx.fillText(label, node.x, node.y + r + fontSize / 2 + 3)
        }
      }, [highlightNodes, selectedNode, palette]
    )

    // Draw edge with relationship label
    const linkCanvasObject = useCallback(
      (link, ctx, globalScale) => {
        const isHighlighted = highlightLinks.size === 0 || highlightLinks.has(link)

        const src = link.source
        const tgt = link.target
        if (!src?.x || !tgt?.x) return

        // Draw line
        ctx.beginPath()
        ctx.moveTo(src.x, src.y)
        ctx.lineTo(tgt.x, tgt.y)
        ctx.strokeStyle = isHighlighted ? 'rgba(129,140,248,0.6)' : palette.dimEdge
        ctx.lineWidth = isHighlighted ? 1.5 : 0.5
        ctx.stroke()

        // Relationship label on highlighted edges
        if (isHighlighted && link.type && globalScale >= 0.8) {
          const midX = (src.x + tgt.x) / 2
          const midY = (src.y + tgt.y) / 2
          const fontSize = Math.max(8 / globalScale, 2)
          const label = link.type.replace(/_/g, ' ').toUpperCase()

          ctx.font = `500 ${fontSize}px Inter,sans-serif`
          const tw = ctx.measureText(label).width
          const pad = fontSize * 0.5

          ctx.fillStyle = 'rgba(30,34,56,0.9)'
          ctx.beginPath()
          ctx.roundRect(midX - tw/2 - pad, midY - fontSize/2 - pad/2, tw + pad * 2, fontSize + pad, 3)
          ctx.fill()

          ctx.fillStyle = '#818cf8'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(label, midX, midY)
        }
      }, [highlightLinks, palette]
    )

    const handleZoomIn = () => {
      graphRef.current?.zoom(graphRef.current.zoom() * 1.3, 300)
    }
    const handleZoomOut = () => {
      graphRef.current?.zoom(graphRef.current.zoom() * 0.75, 300)
    }
    const handleFit = () => {
      graphRef.current?.zoomToFit(400, 60)
    }
    const handleSave = () => {
      const canvas = document.querySelector('canvas')
      if (!canvas) return
      const link = document.createElement('a')
      link.download = `entity-map-${caseId.slice(0,8)}.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
      toast.success('Graph saved as PNG')
    }

    return (
      <div style={{
        position: 'relative',
        width: '100%',
        height: 'calc(100vh - 100px)',
        display: 'flex',
        flexDirection: 'column',
      }}>

        {/* Header row */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12, gap: 12,
          flexShrink: 0,
        }}>
          <div>
            <h1 style={{
              fontSize: 20, fontWeight: 700,
              background: 'linear-gradient(135deg, #fff 30%,#818cf8 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              Entity Relationship Map
            </h1>
            <p style={{
              fontSize: 12, marginTop: 2,
              color: 'var(--color-white-3)',
            }}>
              {filteredData.nodes.length} nodes · {filteredData.links.length} edges
              {search || selectedTypes.length > 0
                ? ` (filtered from ${graphData.nodes.length})`
                : ''}
            </p>
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { icon: ZoomIn, action: handleZoomIn, tip: 'Zoom in' },
              { icon: ZoomOut, action: handleZoomOut, tip: 'Zoom out' },
              { icon: Maximize2, action: handleFit, tip: 'Fit all' },
              { icon: Download, action: handleSave, tip: 'Save PNG' },
              { icon: RefreshCw, action: loadGraph, tip: 'Refresh' },
            ].map(({ icon: Icon, action, tip }) => (
              <button
                key={tip}
                onClick={action}
                title={tip}
                style={{
                  width: 34, height: 34,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: 8,
                  background: 'var(--color-white-04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  cursor: 'pointer',
                  color: 'var(--color-white-4)',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.color = '#818cf8'
                  e.currentTarget.style.borderColor = 'rgba(99,102,241,0.3)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.color = 'var(--color-white-4)'
                  e.currentTarget.style.borderColor = 'var(--color-white-08)'
                }}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>
        </div>

        {/* Type filter + search */}
        <div style={{
          display: 'flex',
          gap: 8, marginBottom: 12,
          flexShrink: 0, flexWrap: 'wrap',
        }}>
          {/* Search */}
          <div style={{ position: 'relative', flex: 1, minWidth: 200 }}>
            <Search size={12} style={{
              position: 'absolute',
              left: 10,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--color-white-2)',
              pointerEvents: 'none',
            }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search entities..."
              style={{
                width: '100%',
                background: 'var(--color-white-04)',
                border: '1px solid rgba(255,255,255,0.09)',
                borderRadius: 8,
                padding: '7px 10px 7px 30px',
                fontSize: 12,
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          </div>

          {/* Type filter chips */}
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {/* All */}
            <button
              onClick={() => setSelectedTypes([])}
              style={{
                padding: '5px 12px',
                borderRadius: 20,
                background: selectedTypes.length === 0 ? 'var(--color-white-1)' : 'var(--color-white-04)',
                border: selectedTypes.length === 0 ? '1px solid rgba(255,255,255,0.3)' : '1px solid rgba(255,255,255,0.08)',
                color: 'var(--text-primary)',
                fontSize: 11, cursor: 'pointer',
              }}>
              All
            </button>
            {Object.entries(NODE_TYPES).filter(([type]) => counts[type] > 0).map(([type, cfg]) => (
              <button
                key={type}
                onClick={() => toggleType(type)}
                style={{
                  padding: '5px 12px',
                  borderRadius: 20,
                  background: selectedTypes.includes(type) ? `${cfg.color}20` : 'var(--color-white-04)',
                  border: selectedTypes.includes(type) ? `1px solid ${cfg.color}50` : '1px solid rgba(255,255,255,0.08)',
                  color: selectedTypes.includes(type) ? cfg.color : 'var(--color-white-5)',
                  fontSize: 11,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                }}>
                <span style={{
                  width: 6, height: 6,
                  borderRadius: '50%',
                  background: cfg.color,
                  flexShrink: 0,
                }} />
                {type}
                <span style={{ opacity: 0.6, fontSize: 10 }}>
                  {counts[type] || 0}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Graph container */}
        <div style={{
          flex: 1, position: 'relative',
          background: 'var(--color-white-03)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 16,
          overflow: 'hidden',
        }}>
          {loading ? (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%', gap: 16,
            }}>
              <RefreshCw size={28}
                color="#818cf8"
                style={{ animation: 'spin 1s linear infinite' }} />
              <p style={{ fontSize: 13, color: 'var(--color-white-4)' }}>
                Building relationship graph...
              </p>
            </div>
          ) : filteredData.nodes.length === 0 ? (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%', gap: 12,
            }}>
              <Link size={40} style={{ color: 'var(--color-white-1)' }} />
              <p style={{ fontSize: 13, color: 'var(--color-white-3)' }}>
                {search || selectedTypes.length > 0
                  ? 'No entities match filters'
                  : 'No entities yet. Ingest evidence first.'}
              </p>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={filteredData}
              nodeId="id"
              nodeLabel={() => ''}
              nodeCanvasObject={nodeCanvasObject}
              nodeCanvasObjectMode={() => 'replace'}
              linkCanvasObject={linkCanvasObject}
              linkCanvasObjectMode={() => 'replace'}
              onNodeClick={handleNodeClick}
              onNodeHover={handleNodeHover}
              backgroundColor="transparent"
              // Physics for better spread
              d3AlphaDecay={0.015}
              d3VelocityDecay={0.25}
              cooldownTime={3000}
              // Link distance
              linkDirectionalArrowLength={0}
              onEngineStop={() => {
                graphRef.current?.zoomToFit(400, 80)
              }}
              width={undefined}
              height={undefined}
            />
          )}

          {/* Node Inspector */}
          {selectedNode && (
            <NodeInspector
              node={selectedNode}
              caseId={caseId}
              navigate={navigate}
              position={popupPos}
              onClose={() => setSelectedNode(null)}
            />
          )}

          {/* Legend */}
          <div style={{
            position: 'absolute',
            bottom: 16, left: 16,
            background: 'rgba(14,15,26,0.9)',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 12,
            padding: '10px 14px',
          }}>
            <p style={{
              fontSize: 9, fontWeight: 600,
              color: 'var(--color-white-3)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 8,
            }}>
              Legend
            </p>
            {Object.entries(NODE_TYPES).filter(([t]) => counts[t] > 0).map(([type, cfg]) => (
              <div key={type} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 7, marginBottom: 5,
              }}>
                <span style={{
                  width: 10, height: 10,
                  borderRadius: '50%',
                  background: cfg.color,
                  flexShrink: 0,
                  boxShadow: `0 0 6px ${cfg.color}88`,
                }} />
                <span style={{ fontSize: 11, color: 'var(--color-white-5)' }}>
                  {type}
                </span>
                <span style={{
                  fontSize: 10,
                  color: 'var(--color-white-2)',
                  marginLeft: 'auto',
                  paddingLeft: 8,
                }}>
                  {counts[type]}
                </span>
              </div>
            ))}
            <div style={{
              marginTop: 8,
              paddingTop: 8,
              borderTop: '1px solid rgba(255,255,255,0.05)',
              fontSize: 10,
              color: 'var(--color-white-2)',
            }}>
              Node size = mention frequency<br />
              Hover to highlight connections<br />
              Click to inspect node
            </div>
          </div>

          {/* Hover tip */}
          {!selectedNode && !hoverNode && filteredData.nodes.length > 0 && (
            <div style={{
              position: 'absolute',
              top: 14, left: '50%',
              transform: 'translateX(-50%)',
              background: 'rgba(14,15,26,0.8)',
              border: '1px solid rgba(255,255,255,0.07)',
              borderRadius: 8,
              padding: '5px 14px',
              fontSize: 11,
              color: 'var(--color-white-3)',
              pointerEvents: 'none',
            }}>
              Hover to highlight · Click to inspect · Scroll to zoom
            </div>
          )}
        </div>
      </div>
    )
  }
