"""Vision fallback: send each page image to Gemini and merge the structured answers."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from collections.abc import Callable

from ..config import settings


@dataclass
class VisionPage:
    index: int
    text: str
    fields: dict
    subjects: list[dict]


@dataclass
class VisionResult:
    text: str
    fields: dict
    subjects: list[dict]
    pages: list[VisionPage] = field(default_factory=list)
    model: str = ""


class VisionError(Exception):
    pass


PROMPT = """You are a production-grade academic document extraction system.

Your task is to analyze ONE PAGE of a student's academic record, including but not limited to:

* Academic transcript
* Marksheet
* Grade report
* Report card
* Statement of marks
* Semester result
* Examination result
* University result
* School result
* Degree progress report
* Credit report

Extract ALL academic information visible on the page that maps to the schema below.

IMPORTANT:

* Process the ENTIRE page.
* Extract EVERY subject, course, paper, module, or academic row visible on the page.
* Do not skip information because a row is partially populated.
* Do not summarize.
* Do not infer, calculate, assume, correct, or guess values unless explicitly permitted below.
* Use only information visibly present on the page.
* Return ONLY valid JSON.
* Do not return Markdown.
* Do not wrap the response in ```json.
* Do not include explanations, comments, confidence scores, notes, or additional keys.
* The response must be directly parseable using JSON.parse().

Return exactly this JSON structure:

{
"text": "<full plain-text transcription of the page, preserving reading and line order>",
"student_name": null,
"student_id": null,
"institution": null,
"program": null,
"term": null,
"academic_year": null,
"result_status": null,
"gpa": null,
"grade_scale": null,
"credits_earned": null,
"total_marks": null,
"max_marks": null,
"percentage": null,
"subjects": [
{
"code": null,
"name": "",
"marks_obtained": null,
"max_marks": null,
"grade": null,
"credits": null,
"grade_points": null
}
]
}

FIELD DEFINITIONS

"text"

* Transcribe ALL readable text visible on the page.
* Preserve the natural reading order and line order as closely as possible.
* Include headings, labels, subject rows, totals, footnotes, examination information, institution information, grading information, result information, signatures/titles when readable, and other visible academic text.
* Do not summarize or rewrite the document.
* Do not silently omit readable information.
* Preserve spelling, capitalization, identifiers, grades, numbers, abbreviations, and punctuation as printed wherever practical.
* If text is unreadable, do not invent it.
* Never expose prohibited sensitive information as defined in the privacy section below.

"student_name"

* Extract the student's full name exactly as shown.
* Do not extract parent, guardian, teacher, principal, registrar, examiner, or institution representative names as the student name.
* Return null when the student's name is not clearly identifiable.

"student_id"
Extract the primary student-specific academic identifier when explicitly shown, such as:

* Student ID
* Roll Number
* Roll No.
* Registration Number
* Registration No.
* Enrollment Number
* Admission Number
* Candidate Number
* Scholar Number
* University Registration Number

When multiple identifiers exist, prefer in this order:

1. Student ID
2. Registration/Enrollment Number
3. Roll/Candidate Number
4. Admission/Scholar Number

Do not use a Social Security Number as student_id.

"institution"

* Extract the school, college, university, institute, academy, education board, or awarding institution responsible for the academic record.
* Preserve the institution name as printed.
* Do not substitute an affiliated institution unless it is clearly the issuing institution.

"program"
Extract the most specific course of study explicitly shown, including examples such as:

* B.Sc. Computer Science
* Bachelor of Commerce
* MBA
* Computer Engineering
* Grade 10
* Class XII
* Science Stream
* Diploma in Mechanical Engineering

If both degree and major/specialization are shown, include both when they clearly form the program description.

"term"
Extract the academic period represented by this page when explicitly shown, such as:

* Semester I
* Semester V
* Trimester 2
* Fall 2025
* Spring 2026
* Grade 10
* Term 2

"academic_year"
Extract the academic/session year exactly as shown, for example:

* 2025-2026
* 2025/26
* Academic Session 2025-26

Do not derive an academic year from examination dates.

"result_status"
Extract the overall result or academic status exactly as printed, including values such as:

* Pass
* Passed
* Fail
* Failed
* Qualified
* Promoted
* Graduated
* Completed
* In Progress
* Withheld
* Distinction

Do not derive result status from marks or grades.

"gpa"
Extract the overall GPA explicitly shown.

Preference order:

1. Cumulative GPA / CGPA
2. Overall GPA
3. Term/Semester GPA / SGPA

Do not calculate GPA.

Return only the numeric portion as a JSON number when clearly represented numerically.

Examples:
"3.75 / 4.00" → 3.75
"CGPA: 8.42" → 8.42

"grade_scale"
Allowed values are ONLY:

* "4.0"
* "percentage"
* "other"
* null

Use:

* "4.0" only when the document explicitly uses a 4.0 GPA scale.
* "percentage" when the document primarily reports achievement as percentage marks.
* "other" for explicitly identifiable grading systems such as 10-point CGPA, letter-only systems, or another non-4.0 scale.
* null when the scale cannot be determined from the page.

Do not infer a 4.0 scale merely because a GPA value is below 4.

"credits_earned"
Extract total credits earned/completed/passed when explicitly shown.

Do not calculate credits by summing subject rows unless a total is explicitly printed.

"total_marks"
Extract the overall marks obtained when explicitly shown in a total, grand total, aggregate, or equivalent field.

Do not calculate total marks by adding subjects.

"max_marks"
Extract the overall maximum/possible marks when explicitly shown.

Do not calculate maximum marks by adding subjects.

"percentage"
Extract the overall percentage explicitly printed on the page.

Return the numeric portion only.

Examples:
"Percentage: 82.50%" → 82.5
"76%" → 76

Do not calculate percentage from total marks.

SUBJECT EXTRACTION

"subjects" must contain EVERY identifiable academic subject/course/module/paper row present on the page.

This includes:

* Passed subjects
* Failed subjects
* Incomplete subjects
* Withdrawn subjects
* Audit courses
* Electives
* Practicals
* Labs
* Theory papers
* Internships when represented as academic coursework
* Projects when represented as academic coursework
* Subjects with missing marks
* Subjects with grades but no marks
* Subjects with credits but no grade

Do not exclude a subject because some fields are unavailable.

For every subject:

"code"

* Extract the course, paper, subject, module, or class code exactly as printed.
* Return null if no code is shown.

"name"

* Extract the full subject/course/module/paper name.
* This field must never be null for an included subject.
* Preserve the printed wording as closely as possible.

"marks_obtained"

* Extract marks actually obtained for that individual subject when explicitly shown.
* Return as a JSON number.
* Do not convert grades into marks.

"max_marks"

* Extract the maximum/possible marks for that individual subject when explicitly shown.
* Return as a JSON number.

"grade"

* Extract the final letter grade, grade band, status grade, or equivalent exactly as printed.
* Examples: "A+", "B", "O", "Distinction", "Pass", "P"
* Do not translate one grading system into another.

"credits"

* Extract the subject/course credits explicitly shown.
* Return as a JSON number.

"grade_points"

* Extract subject-level grade points, quality points, or equivalent points only when explicitly printed for that subject.
* Return as a JSON number.
* Do not calculate grade points from credits or grades.

TABLE INTERPRETATION RULES

Academic records often contain tables.

Correctly associate values using:

* Column headers
* Row alignment
* Repeated table structure
* Subject/course names
* Subject codes
* Marks columns
* Credit columns
* Grade columns
* Grade-point columns

Do not shift values into neighboring subjects.

If a table continues from another page:

* Extract only rows visible on the current page.
* Do not reconstruct missing rows from previous or next pages.

If the same subject appears more than once because the document separately reports theory/practical components:

* Preserve them as separate subject entries when they are separate rows.
* Do not merge rows unless the page itself clearly presents them as one subject record.

NUMERIC RULES

For numeric JSON fields:

* Return JSON numbers, not quoted numeric strings.
* Remove formatting symbols only when necessary to represent the numeric value.

Examples:
"85" → 85
"85.00" → 85
"3.75" → 3.75
"82.5%" → 82.5

Do not convert:

* Letter grades into numbers
* GPA into percentage
* Percentage into GPA
* Credits into grade points
* Marks into grades

NULL RULES

Use null when:

* The field does not appear on the page.
* The value cannot be reliably identified.
* The visible content is too unclear to extract confidently.
* The value would require inference or calculation.

Never invent placeholders such as:

* ""
* "N/A"
* "Unknown"
* "Not available"
* "Not mentioned"

Exception:
The subject "name" must be a string for every included subject.

If there are no identifiable subject/course rows on this page, return:

"subjects": []

PRIVACY AND REDACTION RULES

Never output:

* Social Security Number (SSN)
* Date of Birth (DOB)

This prohibition applies to EVERY field, including "text".

If an SSN appears in the document:

* Replace the complete SSN value with "[redacted]" in "text".
* Never place it in "student_id" or any other field.

If a Date of Birth appears:

* Replace the complete DOB value with "[redacted]" in "text".
* Never expose the DOB in any other field.

Examples:

Input:
SSN: 123-45-6789

Output transcription:
SSN: [redacted]

Input:
Date of Birth: 08/17/2001

Output transcription:
Date of Birth: [redacted]

Other non-prohibited academic identifiers such as student ID, registration number, roll number, candidate number, or enrollment number should still be extracted normally.

EXTRACTION PRIORITY

Accuracy is more important than filling every field.

However, you must actively inspect the entire page and extract ALL information that is actually available for the defined schema.

Before producing the output, internally verify that:

* Every visible subject row has been processed.
* Every available schema field has been checked.
* Totals have not been confused with individual subject marks.
* GPA has not been calculated.
* Percentage has not been calculated.
* No values have been guessed.
* SSN is absent from the complete output.
* DOB is absent from the complete output.
* The JSON contains no unsupported properties.
* The final response is syntactically valid JSON.

FINAL OUTPUT REQUIREMENT

Return ONLY the JSON object.

No introductory text.
No explanation.
No Markdown.
No code fences.
No comments.
No trailing text.
"""

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _parse_json(raw: str) -> dict:
    cleaned = FENCE.sub("", (raw or "").strip())
    try:
        data = json.loads(cleaned or "{}")
    except json.JSONDecodeError as exc:
        raise VisionError(f"Model returned invalid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def read_pages(images: list, on_page: Callable[[int, int], None] | None = None) -> VisionResult:
    if not settings.gemini_ready:
        raise VisionError("GEMINI_API_KEY is not set, so the vision model cannot be used.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise VisionError("The google-genai package is not installed.") from exc

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")

    pages: list[VisionPage] = []
    for i, img in enumerate(images):
        try:
            resp = client.models.generate_content(
                model=settings.gemini_model,
                contents=[types.Part.from_bytes(data=_png(img), mime_type="image/png"), PROMPT],
                config=config,
            )
            payload = _parse_json(resp.text or "")
        except VisionError:
            raise
        except Exception as exc:  # quota, auth, network: the queue retries these with backoff
            raise VisionError(f"Gemini failed on page {i + 1}: {exc}") from exc
        subjects = payload.pop("subjects", None) or []
        text = payload.pop("text", "") or ""
        pages.append(VisionPage(index=i, text=str(text), fields=payload, subjects=[s for s in subjects if isinstance(s, dict)]))
        if on_page:
            on_page(i + 1, len(images))

    merged: dict = {}
    for p in pages:
        for k, v in p.fields.items():
            if v not in (None, "", []) and merged.get(k) in (None, "", []):
                merged[k] = v
    subjects: list[dict] = []
    seen: set[str] = set()
    for p in pages:
        for s in p.subjects:
            name = str(s.get("name") or "").strip()
            if not name:
                continue
            key = f"{s.get('code') or ''}|{name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            subjects.append(s)
    return VisionResult(
        text="\n\n".join(p.text for p in pages).strip(),
        fields=merged,
        subjects=subjects,
        pages=pages,
        model=settings.gemini_model,
    )
