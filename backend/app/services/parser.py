"""Heuristic parser: pull student details and course rows out of academic-record text.

Handles two families of layout:
  * US transcripts: letter grades on a 4.0 scale, credit hours, quality points, Fall/Spring terms, Student ID.
  * Marks-based sheets: marks obtained / maximum marks, percentages, semester numbers.
Structured output from an LLM or Document AI form fields takes precedence over the heuristics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extractor import Extraction


@dataclass
class ParsedSubject:
    code: str | None
    name: str
    marks_obtained: float | None
    max_marks: float | None
    grade: str | None
    credits: float | None
    grade_points: float | None = None


@dataclass
class ParsedRecord:
    student_name: str | None = None
    roll_number: str | None = None
    institution: str | None = None
    program: str | None = None
    term: str | None = None
    academic_year: str | None = None
    result_status: str | None = None
    total_marks: float | None = None
    max_marks: float | None = None
    percentage: float | None = None
    gpa: float | None = None
    credits_earned: float | None = None
    grade_scale: str | None = None  # "4.0" | "percentage" | "other"
    confidence: float = 0.0
    pii_redacted: bool = False
    subjects: list[ParsedSubject] = field(default_factory=list)


# US 4.0 scale (plus/minus). Grades that carry no points (P, W, I, ...) map to None.
GRADE_POINTS: dict[str, float] = {
    "A+": 4.0, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D+": 1.3, "D": 1.0, "D-": 0.7,
    "F": 0.0,
}
NO_POINT_GRADES = {"P", "NP", "S", "U", "W", "I", "IP", "CR", "NC", "AU", "PASS", "FAIL", "AB"}

GRADE_RE = re.compile(
    r"^(A\+\+|[A-D][+-]?|F|O|S|U|P|NP|W|IP|CR|NC|AU|AB|PASS|FAIL|[A-E][1-3])$", re.I
)
NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
CODE_RE = re.compile(r"^[A-Z]{2,6}[-\s]?\d{2,5}[A-Z]{0,2}$|^\d{2,4}[A-Z]{1,3}\d{0,4}$")
NUMERIC_CODE_RE = re.compile(r"^\d{3,6}$")
SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}[-. ](?!00)\d{2}[-. ](?!0000)\d{4}\b")
# Unseparated or oddly punctuated SSNs only count when labelled, so nine-digit student IDs survive.
SSN_LABELLED_RE = re.compile(r"(?i)\b(?:ssn|social\s+security(?:\s+(?:number|no\.?|#))?)\s*[:#\-]?\s*(\d[\d\-. ]{7,12}\d)")
DOB_LINE_RE = re.compile(r"(?im)^(.*\b(?:date\s+of\s+birth|d\.?\s?o\.?\s?b\.?|birth\s*date|born(?:\s+on)?)(?![a-z])\s*[:\-]?\s*)(\S.*)$")

LABELS: dict[str, list[str]] = {
    "student_name": [
        r"(?:student'?s?|candidate'?s?)\s*name",
        r"name\s+of\s+(?:the\s+)?(?:student|candidate)",
        # A bare "Name:" label, but never a parent's, guardian's or teacher's.
        r"(?<!father's )(?<!mother's )(?<!guardian's )(?<!parent's )(?<!father )(?<!mother )(?<!guardian )(?<!teacher )(?<!principal )(?<!examiner )name",
    ],
    "roll_number": [
        r"student\s*(?:id|number|no\.?|#)",
        r"(?:id|identification)\s*(?:number|no\.?|#)",
        r"roll\s*(?:no\.?|number|#)",
        r"registration\s*(?:no\.?|number)",
        r"reg\.?\s*no\.?",
        r"enrol+ment\s*(?:no\.?|number)",
        r"seat\s*(?:no\.?|number)",
        r"hall\s*ticket\s*(?:no\.?|number)",
    ],
    "institution": [
        r"(?:name\s+of\s+(?:the\s+)?)?(?:school|college|institution|institute|university|campus)(?:\s+name)?",
    ],
    "program": [
        r"(?:degree\s+program|program\s+of\s+study|major|degree|course|program(?:me)?|branch|class|standard|stream|grade\s+level)(?:\s*/\s*branch)?",
    ],
    "term": [r"(?:term|semester|sem|quarter|year\s+of\s+study)"],
    "academic_year": [
        r"(?:academic\s+year|school\s+year|session|year\s+of\s+(?:passing|examination|graduation)|exam(?:ination)?\s+(?:year|held\s+in)|month\s*(?:&|and)\s*year)",
    ],
    "result_status": [r"(?:academic\s+standing|standing|result|status|overall\s+result|division)"],
}

INSTITUTION_HINTS = re.compile(
    r"\b(university|college|institute|school|academy|board|vidyalaya|polytechnic|district|campus)\b", re.I
)
PROGRAM_HINTS = re.compile(
    r"\b(b\.?\s?tech|m\.?\s?tech|b\.?\s?sc|m\.?\s?sc|b\.?\s?com|m\.?\s?com|b\.?\s?a|m\.?\s?a|b\.?s\.?|m\.?s\.?|bba|mba|bca|mca|"
    r"ph\.?d|diploma|bachelor|master|associate|class\s+[xiv0-9]+|grade\s+\d+|std\.?\s*\d+|engineering|science|commerce|arts|"
    r"major\s*:|minor\s*:)\b",
    re.I,
)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2}\s*[-/]\s*(?:19|20)?\d{2}|(?:19|20)\d{2})\b")
US_TERM_RE = re.compile(r"\b((?:fall|spring|summer|winter|autumn)\s+(?:semester\s+|quarter\s+|term\s+)?(?:19|20)\d{2})\b", re.I)
SEM_RE = re.compile(r"\b(?:semester|sem)\s*[-:]?\s*([ivx]+|\d+)\b", re.I)
PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
GPA_RE = re.compile(r"\b(?:s?g\.?p\.?a\.?|c\.?g\.?p\.?a\.?)\s*[:=-]?\s*(\d{1,2}(?:\.\d{1,3})?)", re.I)
CUM_GPA_RE = re.compile(r"\b(?:cumulative|cum\.?|overall)\s+g\.?p\.?a\.?\s*[:=-]?\s*(\d{1,2}(?:\.\d{1,3})?)", re.I)
CREDITS_RE = re.compile(
    r"\b(?:total\s+)?(?:credits?|credit\s+hours?|units?)\s+(?:earned|completed|passed)\s*[:=-]?\s*(\d{1,3}(?:\.\d+)?)", re.I
)
TOTAL_RE = re.compile(
    r"\b(?:grand\s+)?total\b[^\d\n]{0,30}(\d{2,5}(?:\.\d+)?)(?:(?:\s*(?:/|out\s+of)\s*|\s+)(\d{2,5})(?![\d.%]))?", re.I
)
RESULT_RE = re.compile(
    r"\b(?:result|status|standing)\s*[:\-]?\s*(pass(?:ed)?|fail(?:ed)?|promoted|graduated|good\s+standing|dean'?s\s+list|"
    r"honou?rs?|probation|first\s+class(?:\s+with\s+distinction)?|second\s+class|distinction|qualified|not\s+qualified|withheld)\b",
    re.I,
)
NOISE_ROW = re.compile(
    r"^(subject|course|paper|s\.?\s*no|sr\.?\s*no|code|total|grand total|aggregate|percentage|result|max|min|marks|obtained|"
    r"grade|credit|term|semester|quarter|cumulative|attempted|earned|points|quality|gpa)",
    re.I,
)
META_LINE = re.compile(
    r"\b(name|roll|reg|date|dob|father|mother|school|college|university|institute|address|phone|email|semester|session|"
    r"s?gpa|cgpa|percentage|total|result|division|rank|attendance|credits?\s+(?:earned|attempted)|ssn|social\s+security)\b",
    re.I,
)
LABELLED_VALUE = re.compile(r"^[A-Za-z .()/&-]{2,40}\s*[:=]\s*\S+$")
# When one line carries two fields ("Name: Sam Okafor   Student ID: NG-2210"), cut before the next label. Only
# real label words count, so a surname followed by spaces is never mistaken for a label.
NEXT_LABEL_RE = re.compile(
    r"\s{2,}|\t|\s+(?=(?:student|candidate|roll|reg(?:istration)?|enrol\w*|id|class|course|program\w*|degree|major|branch|"
    r"term|semester|sem|quarter|year|session|date|dob|result|status|standing|grade|father|mother|guardian|school|college|"
    r"university|institution)\b[^:\n]{0,25}:)",
    re.I,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :-|\t")


def _title(value: str) -> str:
    """Title-case that leaves apostrophes alone: "dean's list" -> "Dean's List", not "Dean'S List"."""
    return re.sub(r"[A-Za-z][A-Za-z']*", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), _clean(value))


def _to_num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    v = str(value).strip().replace(",", "")
    if NUM_RE.match(v):
        return float(v)
    return None


def redact_pii(text: str) -> tuple[str, bool]:
    """Strip SSNs and dates of birth. FERPA/state law: never keep these in the register."""
    redacted, n = SSN_LABELLED_RE.subn(lambda mt: mt.group(0)[: mt.start(1) - mt.start(0)] + "[SSN redacted]", text)
    redacted, n2 = SSN_RE.subn("[SSN redacted]", redacted)
    redacted, m = DOB_LINE_RE.subn(lambda mt: mt.group(1) + "[redacted]", redacted)
    # The vision model redacts at the source and writes "[redacted]"; count that too.
    return redacted, bool(n or n2 or m or "[redacted]" in text.lower())


def _find_label(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        rx = re.compile(r"(?im)^\s*(?:" + pattern + r")\s*[:\-]\s*(.+?)\s*$")
        m = rx.search(text)
        if m:
            candidate = _clean(m.group(1))
            candidate = NEXT_LABEL_RE.split(candidate)[0]
            if candidate and len(candidate) < 120:
                return _clean(candidate)
        rx_inline = re.compile(
            r"(?im)\b(?:" + pattern + r")\s*[:\-]\s*([^:\n]{2,80}?)(?=\s{2,}|\s+(?:student|candidate|roll|reg(?:istration)?|enrol\w*|id|class|course|program\w*|degree|major|branch|term|semester|sem|quarter|year|session|date|dob|result|status|standing|grade|father|mother|guardian|school|college|university|institution)\b[^:\n]{0,25}[:\-]|$)"
        )
        m = rx_inline.search(text)
        if m:
            candidate = _clean(m.group(1))
            if candidate:
                return candidate
    return None


def grade_points_for(grade: str | None) -> float | None:
    if not grade:
        return None
    g = grade.strip().upper()
    if g in NO_POINT_GRADES:
        return None
    return GRADE_POINTS.get(g)


def _parse_subject_line(line: str, cells: list[str] | None = None) -> ParsedSubject | None:
    raw = line.strip()
    if not raw or NOISE_ROW.match(raw):
        return None
    if cells:
        tokens = [c.strip() for c in cells if c.strip()]
    else:
        tokens = re.split(r"\s{2,}|\t|\s*\|\s*", raw)
        if len(tokens) < 2:
            tokens = raw.split()
        tokens = [t.strip() for t in tokens if t.strip()]
    if len(tokens) < 2:
        return None
    leading_code: str | None = None
    if cells and len(tokens) >= 3 and NUMERIC_CODE_RE.match(tokens[0]) and re.search(r"[A-Za-z]{3,}", tokens[1]):
        leading_code = tokens[0]
        tokens = tokens[1:]

    code: str | None = leading_code
    grade: str | None = None
    numbers: list[float] = []
    words: list[str] = []
    # US transcripts print "ENGL 101" as two tokens when split on whitespace.
    if code is None and len(tokens) >= 3 and re.fullmatch(r"[A-Z]{2,6}", tokens[0]) and re.fullmatch(r"\d{2,4}[A-Z]?", tokens[1]):
        code = f"{tokens[0]} {tokens[1]}"
        tokens = tokens[2:]
    for tok in tokens:
        num = _to_num(tok)
        if code is None and CODE_RE.match(tok):
            code = tok
        elif num is not None:
            numbers.append(num)
        elif GRADE_RE.match(tok) and len(tok) <= 4 and grade is None and words:
            grade = tok.upper()
        else:
            words.append(tok)

    first = raw.split()[0]
    if len(numbers) >= 2 and numbers[0] < 30 and numbers[0].is_integer() and first == str(int(numbers[0])):
        numbers = numbers[1:]

    name = _clean(" ".join(words))
    name = re.sub(r"^\d+[.)]?\s*", "", name)
    if not name or len(name) < 2 or len(name) > 90:
        return None
    if not numbers and not grade:
        return None
    if not re.search(r"[A-Za-z]{2,}", name):
        return None

    marks = max_marks = credits = points = None
    letter = grade is not None and (grade in GRADE_POINTS or grade in NO_POINT_GRADES)
    if letter and numbers and all(n <= 20 for n in numbers):
        # US style: credits [grade points]
        credits = numbers[0]
        gp = grade_points_for(grade)
        if len(numbers) >= 2:
            points = numbers[1]
        elif gp is not None:
            points = round(gp * credits, 2)
    elif len(numbers) == 1:
        marks = numbers[0]
    elif len(numbers) >= 2:
        cands = numbers[:]
        if len(numbers) >= 3 and numbers[-1] <= 10 and numbers[-1].is_integer():
            credits = numbers[-1]
            cands = cands[:-1]
        max_marks = max(cands)
        cands.remove(max_marks)
        marks = cands[-1] if cands else None
        if marks is not None and max_marks is not None and marks > max_marks:
            marks, max_marks = max_marks, marks
    return ParsedSubject(code, name, marks, max_marks, grade, credits, points)


def _subjects_from_tables(tables: list[list[list[str | None]]]) -> list[ParsedSubject]:
    found: list[ParsedSubject] = []
    for table in tables:
        for row in table:
            cells = [(c or "").replace("\n", " ").strip() for c in row]
            if not any(cells):
                continue
            line = "  ".join(c for c in cells if c)
            parsed = _parse_subject_line(line, cells=[c for c in cells if c])
            if parsed:
                found.append(parsed)
    return found


def _subjects_from_text(text: str) -> list[ParsedSubject]:
    found: list[ParsedSubject] = []
    for line in text.splitlines():
        if re.search(r"\d", line) and re.search(r"[A-Za-z]{3,}", line):
            if META_LINE.search(line) or LABELLED_VALUE.match(line.strip()):
                continue
            parsed = _parse_subject_line(line)
            if parsed:
                found.append(parsed)
    return found


def _subjects_from_structured(rows: list[dict]) -> list[ParsedSubject]:
    out: list[ParsedSubject] = []
    for r in rows:
        name = _clean(str(r.get("name") or ""))
        if not name:
            continue
        grade = (str(r["grade"]).strip().upper() or None) if r.get("grade") else None
        credits = _to_num(r.get("credits"))
        points = _to_num(r.get("grade_points"))
        if points is None and credits is not None and grade_points_for(grade) is not None:
            points = round(grade_points_for(grade) * credits, 2)  # type: ignore[operator]
        out.append(
            ParsedSubject(
                code=(str(r["code"]).strip() or None) if r.get("code") else None,
                name=name,
                marks_obtained=_to_num(r.get("marks_obtained")),
                max_marks=_to_num(r.get("max_marks")),
                grade=grade,
                credits=credits,
                grade_points=points,
            )
        )
    return out


def _dedupe(subjects: list[ParsedSubject]) -> list[ParsedSubject]:
    seen: set[str] = set()
    out: list[ParsedSubject] = []
    for s in subjects:
        key = (s.code or "") + "|" + s.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _apply_form_fields(rec: ParsedRecord, fields: dict[str, str]) -> None:
    """Document AI form parser output: {label: value}."""
    for key, value in fields.items():
        k = key.lower()
        v = _clean(value)
        if not v:
            continue
        if rec.student_name is None and re.search(r"\bname\b", k) and not re.search(r"school|college|university|course", k):
            rec.student_name = v
        elif rec.roll_number is None and re.search(r"student\s*id|roll|registration|enrol", k):
            rec.roll_number = v
        elif rec.institution is None and re.search(r"school|college|university|institut", k):
            rec.institution = v
        elif rec.program is None and re.search(r"program|degree|major|course|class", k):
            rec.program = v
        elif rec.term is None and re.search(r"term|semester|quarter", k):
            rec.term = v
        elif rec.academic_year is None and re.search(r"year|session", k):
            rec.academic_year = v


def _apply_structured(rec: ParsedRecord, data: dict) -> None:
    """LLM output: trusted over heuristics wherever it gave a value."""
    mapping = {
        "student_name": "student_name",
        "student_id": "roll_number",
        "institution": "institution",
        "program": "program",
        "term": "term",
        "academic_year": "academic_year",
        "result_status": "result_status",
        "grade_scale": "grade_scale",
    }
    for src, dst in mapping.items():
        v = data.get(src)
        if isinstance(v, str) and v.strip():
            setattr(rec, dst, _clean(v))
    for num in ("gpa", "credits_earned", "total_marks", "max_marks", "percentage"):
        v = _to_num(data.get(num))
        if v is not None:
            setattr(rec, num, v)


def parse(extraction: Extraction) -> ParsedRecord:
    text, redacted = redact_pii(extraction.text or "")
    extraction.text = text
    rec = ParsedRecord(pii_redacted=redacted)

    for field_name, patterns in LABELS.items():
        setattr(rec, field_name, _find_label(text, patterns))

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not rec.institution:
        for line in lines[:12]:
            if INSTITUTION_HINTS.search(line) and len(line) < 100 and ":" not in line:
                rec.institution = _clean(line)
                break
    if not rec.program:
        for line in lines[:25]:
            if PROGRAM_HINTS.search(line) and len(line) < 100 and not INSTITUTION_HINTS.search(line):
                rec.program = _clean(line.split(":")[-1])
                break
    m = US_TERM_RE.search(text)
    if m and (not rec.term or re.fullmatch(r"(?i)[ivx]{1,4}|\d{1,2}", rec.term)):
        rec.term = m.group(1).title()
    if not rec.term:
        m = SEM_RE.search(text)
        if m:
            rec.term = f"Semester {m.group(1).upper()}"
    elif re.fullmatch(r"(?i)[ivx]{1,4}|\d{1,2}", rec.term):
        rec.term = f"Semester {rec.term.upper()}"
    if not rec.academic_year:
        m = YEAR_RE.search(text)
        if m:
            rec.academic_year = m.group(1).replace(" ", "")
    if rec.student_name and (len(rec.student_name) > 60 or re.search(r"\d{3,}", rec.student_name)):
        rec.student_name = None

    m = CUM_GPA_RE.search(text) or GPA_RE.search(text)
    if m:
        rec.gpa = float(m.group(1))
    m = CREDITS_RE.search(text)
    if m:
        rec.credits_earned = float(m.group(1))
    m = RESULT_RE.search(text)
    if m:
        rec.result_status = _title(m.group(1))
    elif rec.result_status and len(rec.result_status) > 40:
        rec.result_status = None

    if extraction.form_fields:
        _apply_form_fields(rec, extraction.form_fields)

    subjects: list[ParsedSubject] = []
    if extraction.structured_subjects:
        subjects = _subjects_from_structured(extraction.structured_subjects)
    if len(subjects) < 1:
        subjects = _subjects_from_tables(extraction.tables)
    if len(subjects) < 2:
        subjects = _subjects_from_text(text)
    rec.subjects = _dedupe(subjects)[:60]

    if extraction.structured:
        _apply_structured(rec, extraction.structured)

    # Aggregates
    with_marks = [s for s in rec.subjects if s.marks_obtained is not None]
    lettered = [s for s in rec.subjects if s.grade and (s.grade in GRADE_POINTS or s.grade in NO_POINT_GRADES)]
    if with_marks:
        rec.total_marks = rec.total_marks or round(sum(s.marks_obtained or 0 for s in with_marks), 2)
        if all(s.max_marks for s in with_marks):
            rec.max_marks = rec.max_marks or round(sum(s.max_marks or 0 for s in with_marks), 2)
    m = TOTAL_RE.search(text)
    if m and not extraction.structured:
        rec.total_marks = float(m.group(1))
        if m.group(2):
            rec.max_marks = float(m.group(2))
    if rec.total_marks and rec.max_marks and rec.percentage is None:
        rec.percentage = round(rec.total_marks / rec.max_marks * 100, 2)
    m = PERCENT_RE.search(text)
    if m and 0 < float(m.group(1)) <= 100 and not extraction.structured:
        rec.percentage = float(m.group(1))

    # US 4.0 scale: GPA from credits and grade points when the sheet did not print one.
    if not rec.grade_scale:
        if lettered and len(lettered) >= max(1, len(rec.subjects) // 2) and not with_marks:
            rec.grade_scale = "4.0"
        elif with_marks:
            rec.grade_scale = "percentage"
        elif rec.subjects:
            rec.grade_scale = "other"
    if rec.grade_scale == "4.0":
        graded = [s for s in rec.subjects if s.credits and grade_points_for(s.grade) is not None]
        if graded:
            cred = sum(s.credits or 0 for s in graded)
            pts = sum((s.grade_points if s.grade_points is not None else grade_points_for(s.grade) * (s.credits or 0)) for s in graded)  # type: ignore[operator]
            if rec.gpa is None and cred:
                rec.gpa = round(pts / cred, 2)
        if rec.credits_earned is None:
            earned = [s.credits or 0 for s in rec.subjects if s.credits and (s.grade or "").upper() not in {"F", "W", "NP", "U", "I", "IP"}]
            if earned:
                rec.credits_earned = round(sum(earned), 1)

    score = 0.0
    score += 0.25 if rec.student_name else 0
    score += 0.15 if rec.roll_number else 0
    score += 0.1 if rec.institution else 0
    score += 0.1 if rec.program else 0
    score += min(len(rec.subjects), 5) * 0.06
    score += 0.1 if rec.percentage or rec.gpa else 0
    rec.confidence = round(min(score, 1.0), 2)
    return rec
