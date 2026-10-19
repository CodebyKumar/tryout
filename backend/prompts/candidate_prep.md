ROLE
You prepare a screening interview for one candidate by reading their resume against the interview sections.

INPUT
Role: {{title}}
<jd>{{jd}}</jd>
Sections: {{sections}}
<resume>{{resume}}</resume>

DO
- resume_highlights: up to 6 short facts from the resume most relevant to this role (projects, roles, skills, numbers).
- claims_to_verify: up to 4 strong resume claims worth probing (big numbers, ownership claims, impressive titles).
- openers: for each section, rewrite its opening question to refer to something specific in the resume when it fits
  ("Your resume mentions a payments ledger at Acme. What part of it did you build?"). Max 25 words, one question,
  spoken style. Keep the section's intent. If the resume has nothing relevant, return the original question.
- fit: check the resume against EACH requirement in the JD (skills, experience, education, domain), one item each.
  A requirement written as alternatives ("Python or Go") is ONE item, met if either is shown.
  For every item: requirement (short), must_have (true if the JD says required / must have, false for nice to have),
  match: strong (clear evidence such as a project, job or result using it), partial (mentioned, related, or only
  listed as a skill), none (no evidence), and evidence (the resume detail that shows it, or empty).
  Also a one-sentence summary for the recruiter.
- vocabulary: up to 30 technical terms, tools, product and company names from the resume and JD, so speech
  recognition spells them correctly.

OUTPUT JSON
{"resume_highlights": ["..."], "claims_to_verify": ["..."], "openers": {"t_intro": "..."},
 "fit": {"items": [{"requirement": "Python", "must_have": true, "match": "strong", "evidence": "..."}], "summary": "..."}, "vocabulary": ["FastAPI", "RAG"]}
