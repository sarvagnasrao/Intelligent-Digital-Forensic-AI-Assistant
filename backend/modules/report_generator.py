from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    getSampleStyleSheet, ParagraphStyle)
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable,
    PageBreak, KeepTogether)
from reportlab.lib.enums import (
    TA_LEFT, TA_CENTER, TA_RIGHT)
from datetime import datetime
import os

# IDF AI colour palette
IDF_DARK    = colors.HexColor('#0f1117')
IDF_CARD    = colors.HexColor('#1e2035')
IDF_ACCENT  = colors.HexColor('#6366f1')
IDF_SUCCESS = colors.HexColor('#22c55e')
IDF_WARNING = colors.HexColor('#f59e0b')
IDF_DANGER  = colors.HexColor('#ef4444')
IDF_TEXT    = colors.HexColor('#e2e8f0')
IDF_MUTED   = colors.HexColor('#64748b')
IDF_BORDER  = colors.HexColor('#2d3154')
WHITE       = colors.white
BLACK       = colors.black

def _build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles['title'] = ParagraphStyle(
        'IDFTitle',
        fontSize=22, 
        fontName='Helvetica-Bold',
        textColor=BLACK,
        spaceAfter=6,
        alignment=TA_LEFT
    )
    styles['subtitle'] = ParagraphStyle(
        'IDFSubtitle',
        fontSize=11,
        fontName='Helvetica',
        textColor=colors.HexColor('#374151'),
        spaceAfter=4
    )
    styles['section'] = ParagraphStyle(
        'IDFSection',
        fontSize=13,
        fontName='Helvetica-Bold',
        textColor=BLACK,
        spaceBefore=16,
        spaceAfter=8,
        borderPad=4
    )
    styles['body'] = ParagraphStyle(
        'IDFBody',
        fontSize=9,
        fontName='Helvetica',
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=4,
        leading=14
    )
    styles['mono'] = ParagraphStyle(
        'IDFMono',
        fontSize=8,
        fontName='Courier',
        textColor=colors.HexColor('#374151'),
        spaceAfter=2,
        leading=12
    )
    styles['caption'] = ParagraphStyle(
        'IDFCaption',
        fontSize=8,
        fontName='Helvetica',
        textColor=colors.HexColor('#6b7280'),
        spaceAfter=2
    )
    styles['answer'] = ParagraphStyle(
        'IDFAnswer',
        fontSize=9,
        fontName='Helvetica',
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=4,
        leading=14,
        leftIndent=12,
        borderPad=6
    )
    return styles

def _header_table(case_data: dict, 
                  report_type: str,
                  generated_by: str) -> Table:
    """
    Creates the report header with 
    case info and IDF AI branding.
    """
    now = datetime.utcnow().strftime(
        '%Y-%m-%d %H:%M:%S UTC')

    header_data = [
        [
            Paragraph(
                '<b>INTELLIGENT DIGITAL FORENSIC '
                'AI ASSISTANT</b>',
                ParagraphStyle(
                    'H', fontSize=10,
                    fontName='Helvetica-Bold',
                    textColor=WHITE)
            ),
            Paragraph(
                f'<b>{report_type.upper()}'
                f'</b>',
                ParagraphStyle(
                    'RT', fontSize=11,
                    fontName='Helvetica-Bold',
                    textColor=WHITE,
                    alignment=TA_RIGHT)
            )
        ]
    ]

    header_table = Table(
        header_data,
        colWidths=[12*cm, 6*cm]
    )
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1),
         IDF_ACCENT),
        ('PADDING', (0,0), (-1,-1), 12),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    return header_table

def _case_info_table(case_data: dict,
                     styles: dict) -> Table:
    """Case metadata table."""
    rows = [
        ['Case Name',
         case_data.get('case_name', 'N/A')],
        ['Case Number',
         case_data.get('case_number', 
                       'Not assigned')],
        ['Status',
         case_data.get('status', 'N/A')],
        ['Priority',
         case_data.get('priority', 'N/A')],
        ['Investigator',
         case_data.get('created_by', 'N/A')],
        ['Created',
         str(case_data.get(
             'created_at', 'N/A'))[:19]],
        ['Case ID',
         case_data.get('id', 'N/A')],
    ]

    table_data = [
        [Paragraph(f'<b>{k}</b>', 
                   styles['caption']),
         Paragraph(str(v), styles['body'])]
        for k, v in rows
    ]

    t = Table(table_data,
              colWidths=[4*cm, 14*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1),
         colors.HexColor('#f9fafb')),
        ('GRID', (0,0), (-1,-1),
         0.5, colors.HexColor('#e5e7eb')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS', (0,0), (-1,-1),
         [colors.white,
          colors.HexColor('#f9fafb')]),
    ]))
    return t

def _evidence_table(evidence_list: list,
                    styles: dict) -> Table:
    """Evidence inventory table."""
    if not evidence_list:
        return Paragraph(
            'No evidence files ingested.',
            styles['body'])

    headers = ['Filename', 'Status',
               'Chunks', 'Entities',
               'SHA-256 (first 16)']
    rows = [headers]

    for e in evidence_list:
        rows.append([
            str(e.get(
                'original_filename', 
                e.get('filename', 'N/A'))
            )[:40],
            str(e.get('status', 'N/A')),
            str(e.get('chunk_count', 0)),
            str(e.get('entity_count', 0)),
            str(e.get(
                'sha256_hash', 'N/A'))[:16]
            + '...'
        ])

    t = Table(
        rows,
        colWidths=[5*cm, 2.5*cm,
                   2*cm, 2*cm, 6.5*cm]
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0),
         colors.HexColor('#374151')),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0),
         'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1),
         0.5, colors.HexColor('#e5e7eb')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
         [colors.white,
          colors.HexColor('#f9fafb')]),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    return t

def _entity_table(entities: list,
                  styles: dict) -> Table:
    """Top entities table."""
    if not entities:
        return Paragraph(
            'No entities extracted.',
            styles['body'])

    type_colors = {
        'Person':       '#fee2e2',
        'Location':     '#d1fae5',
        'Organization': '#fef3c7',
        'IP':           '#ede9fe',
        'File':         '#dcfce7',
    }

    headers = ['Entity', 'Type',
               'Frequency', 'Flagged']
    rows = [headers]

    for e in entities[:50]:
        rows.append([
            str(e.get('name', 'N/A'))[:40],
            str(e.get('entity_type', 'N/A')),
            str(e.get('frequency', 0)),
            '⚑' if e.get('is_flagged')
                else ''
        ])

    t = Table(
        rows,
        colWidths=[7*cm, 3*cm,
                   2.5*cm, 5.5*cm]
    )
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0),
         colors.HexColor('#374151')),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0),
         'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1),
         0.5, colors.HexColor('#e5e7eb')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
         [colors.white,
          colors.HexColor('#f9fafb')]),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    return t

def _query_section(queries: list,
                   styles: dict) -> list:
    """Builds Q&A transcript elements."""
    elements = []
    if not queries:
        elements.append(Paragraph(
            'No queries recorded.',
            styles['body']))
        return elements

    for i, q in enumerate(queries, 1):
        # Question block
        q_data = [[
            Paragraph(
                f'<b>Q{i}.</b> '
                f'{q.get("question_text", "")}',
                styles['body']
            )
        ]]
        q_table = Table(
            q_data, colWidths=[18*cm])
        q_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1),
             colors.HexColor('#eff6ff')),
            ('PADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1),
             12),
            ('ROUNDEDCORNERS', [4,4,4,4]),
        ]))
        elements.append(q_table)
        elements.append(Spacer(1, 4))

        # Answer block
        answer_text = q.get(
            'processed_response', 
            q.get('answer', 
                  'No response recorded')
        ) or 'No response recorded'

        # Clean markdown-style formatting
        answer_clean = answer_text\
            .replace('**', '')\
            .replace('*', '')\
            .replace('\n', '<br/>')

        a_data = [[
            Paragraph(
                f'<b>Analysis:</b><br/>'
                f'{answer_clean}',
                styles['answer']
            )
        ]]
        a_table = Table(
            a_data, colWidths=[18*cm])
        a_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1),
             colors.HexColor('#f9fafb')),
            ('PADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1),
             12),
            ('BORDERPADDING',
             (0,0), (-1,-1), 4),
        ]))
        elements.append(a_table)

        # Metadata row
        meta = (
            f"Asked by: "
            f"{q.get('asked_by', 'N/A')} · "
            f"Model: "
            f"{q.get('model_used', 'N/A')} · "
            f"Response: "
            f"{q.get('response_time_ms', 0)}"
            f"ms · "
            f"Cited sentences: "
            f"{q.get('cited_sentence_count',0)}"
        )
        elements.append(Paragraph(
            meta, styles['caption']))
        elements.append(Spacer(1, 10))

    return elements

def _timeline_section(
        timeline_data: dict,
        styles: dict) -> list:
    """Builds timeline summary elements."""
    elements = []
    if (not timeline_data or
        not timeline_data.get('timeline')):
        elements.append(Paragraph(
            'No timeline data available.',
            styles['body']))
        return elements

    tl = timeline_data['timeline']
    anomalies = [
        d for d in tl if d['is_anomaly']]

    elements.append(Paragraph(
        f"Total events: "
        f"{timeline_data.get('total_events',0)}"
        f" · Date range: "
        f"{timeline_data.get('date_range',{}).get('first','N/A')}"
        f" to "
        f"{timeline_data.get('date_range',{}).get('last','N/A')}",
        styles['body']
    ))
    elements.append(Spacer(1, 6))

    if anomalies:
        elements.append(Paragraph(
            f'⚠ {len(anomalies)} anomalous '
            f'date(s) detected '
            f'(>20 events/day):',
            ParagraphStyle(
                'Warn', fontSize=9,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor(
                    '#b45309'))
        ))
        for day in anomalies:
            elements.append(Paragraph(
                f"  • {day['date']}: "
                f"{day['event_count']} events",
                styles['body']
            ))
        elements.append(Spacer(1, 6))

    # Show top 30 timeline days
    rows = [['Date', 'Events', 'Anomaly']]
    for day in tl[:30]:
        rows.append([
            day['date'],
            str(day['event_count']),
            '⚠ YES' if day['is_anomaly']
                    else 'No'
        ])

    t = Table(rows,
              colWidths=[4*cm, 3*cm, 3*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0),
         colors.HexColor('#374151')),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0),
         'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1),
         0.5, colors.HexColor('#e5e7eb')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
         [colors.white,
          colors.HexColor('#f9fafb')]),
    ]))
    elements.append(t)
    return elements

def _flagged_section(
        artifacts: list,
        entities: list,
        queries: list,
        styles: dict) -> list:
    """Lists all flagged items."""
    elements = []

    flagged_artifacts = [
        a for a in artifacts 
        if a.get('is_flagged')]
    flagged_entities = [
        e for e in entities 
        if e.get('is_flagged')]
    flagged_queries = [
        q for q in queries 
        if q.get('is_flagged')]

    total = (len(flagged_artifacts) +
             len(flagged_entities) +
             len(flagged_queries))

    if total == 0:
        elements.append(Paragraph(
            'No items flagged by investigator.',
            styles['body']))
        return elements

    if flagged_artifacts:
        elements.append(Paragraph(
            f'<b>Flagged Artifacts '
            f'({len(flagged_artifacts)})'
            f':</b>',
            styles['body']))
        for a in flagged_artifacts:
            elements.append(Paragraph(
                f"  ⚑ "
                f"{a.get('internal_path','N/A')}"
                f" [{a.get('sha256_hash','')[:12]}"
                f"...]",
                styles['mono']))
        elements.append(Spacer(1, 6))

    if flagged_entities:
        elements.append(Paragraph(
            f'<b>Flagged Entities '
            f'({len(flagged_entities)})'
            f':</b>',
            styles['body']))
        for e in flagged_entities:
            elements.append(Paragraph(
                f"  ⚑ "
                f"{e.get('name','N/A')} "
                f"[{e.get('entity_type','N/A')}"
                f"]",
                styles['mono']))
        elements.append(Spacer(1, 6))

    if flagged_queries:
        elements.append(Paragraph(
            f'<b>Flagged Queries '
            f'({len(flagged_queries)})'
            f':</b>',
            styles['body']))
        for q in flagged_queries:
            elements.append(Paragraph(
                f"  ⚑ "
                f"{q.get('question_text','N/A')[:80]}...",
                styles['mono']))

    return elements

def _footer(canvas, doc):
    """Page footer with page numbers."""
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(
        colors.HexColor('#9ca3af'))
    page_num = canvas.getPageNumber()
    canvas.drawString(
        2*cm, 1.2*cm,
        'INTELLIGENT DIGITAL FORENSIC AI ASSISTANT'
        ' — CONFIDENTIAL'
    )
    canvas.drawRightString(
        19*cm, 1.2*cm,
        f'Page {page_num}'
    )
    canvas.drawCentredString(
        10.5*cm, 1.2*cm,
        f'Generated: '
        f'{datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}'
    )
    canvas.restoreState()

def generate_report(
        output_path: str,
        report_type: str,
        case_data: dict,
        generated_by: str,
        evidence_list: list = None,
        entities: list = None,
        queries: list = None,
        artifacts: list = None,
        timeline_data: dict = None
) -> int:
    """
    Generates a PDF report at output_path.
    Returns page count.
    
    report_type values:
      Case Summary
      Query Transcript
      Entity Report
      Timeline Report
      Full Investigation
    """
    os.makedirs(
        os.path.dirname(output_path),
        exist_ok=True
    )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2.5*cm,
        title=f'IDF AI Assistant — {report_type}',
        author='Intelligent Digital Forensic AI Assistant'
    )

    styles = _build_styles()
    elements = []
    evidence_list = evidence_list or []
    entities     = entities or []
    queries      = queries or []
    artifacts    = artifacts or []

    # ── Header ──────────────────────────
    elements.append(
        _header_table(
            case_data, report_type, 
            generated_by))
    elements.append(Spacer(1, 12))

    # ── Case Info ───────────────────────
    elements.append(Paragraph(
        'Case Information', 
        styles['section']))
    elements.append(HRFlowable(
        width='100%', thickness=1,
        color=colors.HexColor('#e5e7eb'),
        spaceAfter=8))
    elements.append(
        _case_info_table(case_data, styles))
    elements.append(Spacer(1, 8))

    # ── Sections by report type ─────────
    include_evidence = report_type in (
        'Case Summary', 
        'Full Investigation')
    include_entities = report_type in (
        'Case Summary', 'Entity Report',
        'Full Investigation')
    include_queries  = report_type in (
        'Query Transcript',
        'Full Investigation')
    include_timeline = report_type in (
        'Timeline Report',
        'Full Investigation')
    include_flagged  = report_type in (
        'Case Summary',
        'Full Investigation')

    if include_evidence:
        elements.append(Paragraph(
            'Evidence Inventory',
            styles['section']))
        elements.append(HRFlowable(
            width='100%', thickness=1,
            color=colors.HexColor('#e5e7eb'),
            spaceAfter=8))
        elements.append(
            _evidence_table(
                evidence_list, styles))
        elements.append(Spacer(1, 8))

    if include_entities and entities:
        elements.append(Paragraph(
            f'Extracted Entities '
            f'(top {min(50, len(entities))} '
            f'of {len(entities)})',
            styles['section']))
        elements.append(HRFlowable(
            width='100%', thickness=1,
            color=colors.HexColor('#e5e7eb'),
            spaceAfter=8))
        elements.append(
            _entity_table(entities, styles))
        elements.append(Spacer(1, 8))

    if include_queries and queries:
        elements.append(PageBreak())
        elements.append(Paragraph(
            f'Query Transcript '
            f'({len(queries)} queries)',
            styles['section']))
        elements.append(HRFlowable(
            width='100%', thickness=1,
            color=colors.HexColor('#e5e7eb'),
            spaceAfter=8))
        elements += _query_section(
            queries, styles)

    if include_timeline and timeline_data:
        elements.append(PageBreak())
        elements.append(Paragraph(
            'Forensic Timeline',
            styles['section']))
        elements.append(HRFlowable(
            width='100%', thickness=1,
            color=colors.HexColor('#e5e7eb'),
            spaceAfter=8))
        elements += _timeline_section(
            timeline_data, styles)
        elements.append(Spacer(1, 8))

    if include_flagged:
        elements.append(Paragraph(
            'Flagged Items',
            styles['section']))
        elements.append(HRFlowable(
            width='100%', thickness=1,
            color=colors.HexColor('#e5e7eb'),
            spaceAfter=8))
        elements += _flagged_section(
            artifacts, entities,
            queries, styles)

    # ── Build PDF ───────────────────────
    doc.build(
        elements,
        onFirstPage=_footer,
        onLaterPages=_footer
    )

    # Return page count
    return doc.page
