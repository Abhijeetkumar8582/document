"""Sample academic documents built in memory for smoke tests. Nothing is written to disk."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def marksheet_pdf(
    name: str = "Priya Sharma",
    roll: str = "2K21/CO/312",
    institution: str = "Delhi Technological University",
    program: str = "B.Tech Computer Engineering",
    semester: str = "Semester V",
    session: str = "2023-24",
    rows: list[tuple[str, str, int, int, str, int | None]] | None = None,
) -> bytes:
    rows = rows or [
        ("CO301", "Design and Analysis of Algorithms", 82, 100, "A", 4),
        ("CO303", "Operating Systems", 76, 100, "B+", 4),
        ("CO305", "Computer Networks", 88, 100, "A+", 4),
        ("CO307", "Database Management Systems", 91, 100, "A+", 4),
        ("HU301", "Engineering Economics", 69, 100, "B", 2),
        ("CO309", "Software Engineering Lab", 94, 100, "A+", 2),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(institution, styles["Title"]),
        Paragraph("STATEMENT OF MARKS", styles["Heading2"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Student Name: {name}", styles["Normal"]),
        Paragraph(f"Roll No: {roll}", styles["Normal"]),
        Paragraph(f"Course: {program}", styles["Normal"]),
        Paragraph(f"Semester: {semester}", styles["Normal"]),
        Paragraph(f"Academic Year: {session}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    data = [["Code", "Subject", "Marks Obtained", "Max Marks", "Grade", "Credits"]]
    for code, subject, marks, mx, grade, credits in rows:
        data.append([code, subject, str(marks), str(mx), grade, "" if credits is None else str(credits)])
    total, max_total = sum(r[2] for r in rows), sum(r[3] for r in rows)
    data.append(["", "Total", str(total), str(max_total), "", ""])
    table = Table(data, colWidths=[22 * mm, 70 * mm, 28 * mm, 24 * mm, 18 * mm, 18 * mm])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    story += [table, Spacer(1, 6 * mm), Paragraph(f"Percentage: {round(total / max_total * 100, 2)}%", styles["Normal"]), Paragraph("Result: PASS", styles["Normal"])]
    doc.build(story)
    return buf.getvalue()


def us_transcript_txt(name: str = "Jordan Reyes", student_id: str = "LCC-00417") -> bytes:
    return (
        "Lakeview Community College\nOFFICIAL TRANSCRIPT\n"
        f"Student Name: {name}\nStudent ID: {student_id}\nDegree Program: Associate of Science, Biology\nTerm: Fall 2025\n\n"
        "Course                       Credits  Grade  Points\n"
        "BIO 101  General Biology I     4.0      A      16.0\n"
        "CHM 110  Intro Chemistry       3.0      B+     9.9\n"
        "ENG 101  Composition I         3.0      A-     11.1\n"
        "Cumulative GPA: 3.70\nCredits Earned: 10.0\nAcademic Standing: Dean's List\n"
    ).encode()


def scan_pdf() -> bytes:
    """A PDF that is only a picture of a page: no text layer, so it exercises the scan engines."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((120, 120), "Northgate High School  -  REPORT CARD", fill="black")
    d.text((120, 200), "Student Name: Sam Okafor     Student ID: NG-2210", fill="black")
    y = 300
    for row in ["ENG 11  English Literature   1.0   A", "ALG 2   Algebra II           1.0   B+", "CHM 1   Chemistry            1.0   A-"]:
        d.text((120, y), row, fill="black")
        y += 60
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    return buf.getvalue()
