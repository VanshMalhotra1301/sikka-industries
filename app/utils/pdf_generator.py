import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_sales_summary_pdf(sales_records):
    """
    Compiles an executive-ready business sales transaction brief into an immutable PDF stream.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Define document typography layouts
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'],
        fontName='Helvetica-Bold', fontSize=22, textColor=colors.HexColor('#0F172A'),
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'],
        fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#64748B'),
        spaceAfter=20
    )
    
    # Render Structural Header Block Details
    story.append(Paragraph("SIKHA GROUP OF INDUSTRIES", title_style))
    story.append(Paragraph("Executive Management Brief - Automated Corporate Sales Ledger Report", subtitle_style))
    story.append(Spacer(1, 12))
    
    # Establish Tabular Data Arrays
    table_data = [["Invoice ID", "Timestamp Date", "Dealer Name", "Settlement", "Total Sum Value"]]
    
    grand_total_turnover = 0.0
    for s in sales_records:
        grand_total_turnover += s.total_amount
        table_data.append([
            f"#{s.id}",
            s.date.strftime('%Y-%m-%d'),
            s.customer.name,
            s.payment_mode,
            f"INR {s.total_amount:,.2f}"
        ])
        
    # Append calculated sum row metrics to base layout matrixes
    table_data.append(["", "", "", "Total Turnover:", f"INR {grand_total_turnover:,.2f}"])
    
    # Apply styling matrices rules directly onto report canvases
    sales_table = Table(table_data, colWidths=[60, 80, 200, 80, 110])
    sales_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.HexColor('#F8FAFC'), colors.white]),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#E2E8F0')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (3, -1), (-1, -1), 1.5, colors.HexColor('#0F172A')),
    ]))
    
    story.append(sales_table)
    doc.build(story)
    
    buffer.seek(0)
    return buffer