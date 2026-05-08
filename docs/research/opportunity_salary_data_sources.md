# Opportunity & Salary Heatmap Data Sources

## Purpose

This document evaluates future data providers for the VeriBridge AI Opportunity & Salary Heatmap. The MVP should use mock/static market data first, while the product architecture prepares for pluggable job, wage, and labor-market providers after API keys and usage approvals are available.

The heatmap should help students understand market alignment, not label students as low-cost candidates.

## Ethical Positioning

VeriBridge AI must not rank, recommend, or market students as "cheap labor." The product should use language such as:

- Compensation fit
- Market alignment
- Salary range alignment
- Opportunity density
- Location comparison
- Work authorization fit

Avoid language such as:

- Cheap candidate
- Low-cost student
- Bargain hire
- Discount labor
- Cost-saving talent

The heatmap should support informed student decisions and fair employer expectations. It should not encourage employers to underpay students or international candidates.

## MVP Approach

For the MVP:

1. Use mock/static market data.
2. Define a provider abstraction before integrating external APIs.
3. Store source metadata with every market data record.
4. Plug in real APIs later after provider keys, quotas, legal review, and caching rules are available.

Recommended MVP abstraction:

```text
MarketDataProvider
  searchOpenRoles(query, location, filters)
  getSalaryRange(role, location, seniority)
  getLocationComparison(role, locations)
  getCompetitionSignal(role, location)
  getProviderMetadata()
```

The MVP static dataset should include:

- Role family, such as software engineering intern, data analyst intern, product intern.
- Location, such as city, state, country, remote.
- Estimated open role count.
- Salary range or hourly range.
- Competition level.
- Work authorization notes where available.
- Last updated date.
- Source label, initially `mock`.

## Opportunity & Salary Heatmap Concepts

### Open Role Estimate

An estimated count of currently visible openings for a role and location. In the MVP this can be a static or mock count. Later it can combine job-posting APIs, company career pages, and government labor demand indicators.

### Salary Range

A low, median, and high compensation band for the role and location. For internships and entry-level roles, hourly pay may be more useful than annual salary. Salary data should always show source and freshness.

### Location Comparison

A side-by-side view of opportunity and compensation signals across locations. Example fields:

- Open role estimate.
- Median salary or hourly wage.
- Remote availability.
- Cost-of-living-adjusted note if added later.
- Work authorization constraints.

### Competition Level

A directional signal, not a precise ranking. It can be modeled as `low`, `medium`, or `high` using role density, candidate supply proxy, job freshness, and number of applicants if a provider exposes it.

Competition level should not be presented as a judgment of the student. It is a market condition signal.

### Work Authorization Fit

A compatibility signal between the student's stated work authorization needs and the job's posted requirements. This should be based only on explicit job posting language or verified employer policy data.

Do not infer visa sponsorship from company size, brand reputation, or anecdotal data unless the source is clearly labeled and reviewed.

### Compensation Fit

A comparison between the posted or estimated compensation range and the student's stated target range. Use "compensation fit" and "market alignment" language.

Do not frame lower student expectations as an employer advantage.

## Data Source Summary

| Source | Data Type | Cost Note | Coverage | Best MVP/Future Use |
| --- | --- | --- | --- | --- |
| Adzuna API | Job postings, salary trends, vacancy counts | Free developer access with default limits; commercial use may require approval or higher limits | Multi-country, job-posting and labor-market data | Early real job-posting provider and vacancy/salary trend source |
| JSearch / RapidAPI | Real-time job postings and salary data from Google for Jobs/public job boards | RapidAPI providers may be free, freemium, pay-per-use, or paid depending on selected plan | Global/job-posting-focused | Fast job search aggregation once API keys are available |
| BLS Public Data API / OEWS | U.S. occupational employment and wage statistics | Public/free government data | U.S.-only labor and wage data | Authoritative salary and employment baseline |
| Government labor market data | Public wage, employment, occupation, and training data | Usually free/public, but APIs vary by agency | Usually country-specific or region-specific | Ground-truth market baselines and regional comparisons |
| Company career pages | Employer-owned open roles and role details | Free to view; integration cost is scraping/API maintenance and legal review | Company-specific, global where company publishes roles | Later direct employer opportunity source |

## Source Details

## 1. Adzuna API

Links:

- [Adzuna Developer Portal](https://developer.adzuna.com/)
- [Adzuna API Overview](https://developer.adzuna.com/overview)
- [Adzuna Terms of Service](https://developer.adzuna.com/docs/terms_of_service)

### What Data It Provides

Adzuna provides job advert search endpoints and employment data endpoints. The public documentation describes:

- Job ad listings by keyword and location.
- Salary and vacancy trend endpoints.
- Salary histogram data.
- Regional vacancy data.
- Top companies data.
- Job categories.

### Free Tier or Cost Note

Adzuna requires an `app_id` and `app_key`. Its published default API access limits include 25 hits per minute, 250 hits per day, 1,000 hits per week, and 2,500 hits per month. The terms indicate larger commercial, government, or academic use may require approval or a trial/limit increase discussion.

Current cost and limits should be rechecked before implementation because provider terms can change.

### Best Use in VeriBridge

Adzuna is a strong candidate for the first real job-posting provider because it exposes both live listings and market-style employment data.

Potential uses:

- Open role estimate by role and location.
- Job posting examples for a location.
- Salary trend enrichment where available.
- Vacancy count by region or company.
- Early validation of the heatmap provider abstraction.

### Limitations

- Requires API keys.
- Default rate limits are low for production usage.
- Coverage quality may vary by country, role, and location.
- Commercial usage terms need review before using in a paid product.
- Job posting data can be duplicated, stale, or inconsistently categorized.

### Coverage Classification

Multi-country and job-posting-focused, with some labor-market-style salary and vacancy endpoints.

## 2. JSearch / RapidAPI

Links:

- [OpenWeb Ninja JSearch](https://www.openwebninja.com/api/jsearch)
- [JSearch on RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch/pricing)
- [RapidAPI Pricing Model Documentation](https://docs.rapidapi.com/v2.0.0/docs/api-pricing)

### What Data It Provides

JSearch is positioned as a real-time jobs API using Google for Jobs and public web job-board data. Public materials describe:

- Job search by title, company, keyword, and location.
- Job title, employer, location, employment type, description, and apply link.
- Salary estimates where available.
- Employer information.
- Advanced filtering.

### Free Tier or Cost Note

JSearch is commonly accessed through RapidAPI or OpenWeb Ninja. RapidAPI supports free, freemium, pay-per-use, and paid API pricing models; the exact JSearch plan should be checked at integration time.

Treat this as low-cost/prototype-friendly only after confirming the active plan, quota, and overage pricing.

### Best Use in VeriBridge

JSearch is useful for broad job-posting search and rapid prototyping of live opportunity density.

Potential uses:

- Open role estimate by keyword and location.
- Job-posting examples behind a heatmap cell.
- Remote role filtering.
- Employer and job description enrichment.
- Salary estimates when available in the API response.

### Limitations

- Pricing and quotas depend on the selected marketplace plan.
- Aggregated job search APIs can include duplicates or stale postings.
- Salary data may be estimated or missing.
- Source provenance may vary by posting.
- Reliance on third-party aggregation creates vendor and terms-of-service risk.

### Coverage Classification

Global/job-posting-only focus, with salary data where available.

## 3. BLS Public Data API / OEWS

Links:

- [BLS Public Data API](https://www.bls.gov/bls/api_features.htm)
- [BLS OEWS Home](https://www.bls.gov/oes/)
- [BLS OEWS Data Tables](https://www.bls.gov/oes/tables.htm)
- [BLS OEWS Data Overview](https://www.bls.gov/oes/data-overview.htm)

### What Data It Provides

The BLS Public Data API provides published historical time series data in JSON or Excel formats. OEWS provides occupational employment and wage estimates for hundreds of occupations across:

- United States national estimates.
- State estimates.
- Metropolitan and nonmetropolitan area estimates.
- Industry-specific national estimates.
- Wage measures such as low, median, mean, and high bands depending on table.
- Employment estimates by occupation and geography.

### Free Tier or Cost Note

BLS data is public and free. The BLS API is open for public use and does not require registration for basic access, though registration may be useful for higher limits or production use depending on current BLS API policy.

### Best Use in VeriBridge

BLS/OEWS should be the authoritative U.S. salary and employment baseline.

Potential uses:

- Salary range by occupation and location.
- Employment concentration by location.
- Location comparison for U.S. roles.
- Compensation fit baseline when job postings do not include salary.
- Market alignment explanations using government data.

### Limitations

- U.S.-only.
- Occupational categories may be broader than student job titles.
- Data is not real-time and may lag current market conditions.
- Does not provide individual job postings.
- Internship-specific compensation may not be directly represented.
- Requires mapping VeriBridge role families to SOC/OEWS occupation codes.

### Coverage Classification

U.S.-only labor and wage data, not job-posting data.

## 4. Government Labor Market Data

Links:

- [CareerOneStop Web APIs](https://www.careeronestop.org/Developers/WebAPI/web-api.aspx)
- [CareerOneStop Salary Finder](https://www.careeronestop.org/Toolkit/Wages/find-salary.aspx)
- [BLS OEWS](https://www.bls.gov/oes/)

### What Data It Provides

Government labor market sources can provide:

- Wage ranges.
- Occupational employment.
- Projected growth.
- Job openings by occupation.
- Training and education requirements.
- Regional labor market indicators.
- Career profile data.

CareerOneStop, sponsored by the U.S. Department of Labor, offers APIs for career, employment, and education data. Its salary finder uses BLS OEWS wage data.

### Free Tier or Cost Note

Many government labor datasets are free/open data. APIs may require registration, usage approval, or attribution. Terms vary by agency and country.

### Best Use in VeriBridge

Government data should provide stable, explainable baselines for salary and regional market context.

Potential uses:

- U.S. market alignment baseline.
- Wage comparison by state or metro.
- Occupation profile enrichment.
- Career path context.
- Future international datasets by country.

### Limitations

- Usually country-specific.
- Not always real-time.
- API formats and documentation quality vary.
- Some datasets are bulk downloads rather than APIs.
- Occupation mappings may be coarse.
- International comparability can be difficult because definitions differ by country.

### Coverage Classification

Usually government-region-specific. For BLS and CareerOneStop, U.S.-only labor and wage data.

## 5. Company Career Pages Later

### What Data It Provides

Company career pages can provide employer-owned open role data:

- Current openings.
- Role title.
- Location or remote status.
- Team/department.
- Job description.
- Required qualifications.
- Preferred qualifications.
- Posted compensation where legally disclosed.
- Work authorization or sponsorship statements when explicitly posted.

### Free Tier or Cost Note

Career pages are generally free to view, but integration is not free operationally. Access may require:

- Scraping infrastructure.
- ATS integrations.
- Partner APIs.
- Legal and terms-of-service review.
- Deduplication and normalization.
- Monitoring for page structure changes.

### Best Use in VeriBridge

Company career pages are best as a later-stage direct source for employer-specific roles.

Potential uses:

- Verified employer open roles.
- Employer-specific heatmap cells.
- Direct role recommendations.
- Work authorization language extraction.
- Salary range extraction where posted.

### Limitations

- No universal schema.
- Scraping can violate terms if not reviewed.
- Pages change frequently.
- Duplicate roles may appear across ATS systems and aggregators.
- Compensation and work authorization may be absent.
- Global companies may publish regional career sites separately.

### Coverage Classification

Company-specific, job-posting-only data. Can be global if the company publishes global roles.

## Provider Abstraction Requirements

The future provider layer should normalize all sources into common internal records.

### Normalized Role Opportunity Record

```json
{
  "provider": "adzuna",
  "provider_record_id": "string",
  "role_title": "Software Engineering Intern",
  "role_family": "software_engineering",
  "company": "Example Co",
  "location": {
    "city": "New York",
    "region": "NY",
    "country": "US",
    "remote_status": "hybrid"
  },
  "open_role_signal": {
    "count": 42,
    "confidence": "medium",
    "method": "job_posting_count"
  },
  "salary": {
    "min": 25,
    "median": 35,
    "max": 48,
    "currency": "USD",
    "period": "hourly",
    "source_type": "posting_or_estimate"
  },
  "competition_level": "medium",
  "work_authorization": {
    "sponsorship_signal": "unknown",
    "evidence": null
  },
  "source_url": "https://example.com/job",
  "last_seen_at": "2026-05-08T00:00:00Z",
  "source_freshness": "current_posting"
}
```

### Provider Metadata

Each provider result should include:

- Provider name.
- Provider version or endpoint.
- Retrieval timestamp.
- Source URL where available.
- Data freshness.
- Whether salary is posted, estimated, government baseline, or mock.
- Whether the record is a job posting, labor-market statistic, or company career page role.

## Heatmap Scoring Guidance

The heatmap should combine multiple signals without overclaiming precision.

Suggested MVP labels:

- Opportunity: `low`, `medium`, `high`
- Compensation fit: `below target`, `aligned`, `above target`, `unknown`
- Competition level: `low`, `medium`, `high`, `unknown`
- Work authorization fit: `likely fit`, `needs review`, `not enough information`, `not a fit`
- Data confidence: `mock`, `low`, `medium`, `high`

Avoid exact scoring unless the underlying source supports it. Prefer transparent labels and source notes.

## Recommended Integration Order

1. Mock/static provider.
2. BLS/OEWS static import for U.S. wage baselines.
3. Adzuna API for real job-posting counts and salary/vacancy trends.
4. JSearch/RapidAPI for broader global job-posting coverage.
5. CareerOneStop APIs for U.S. career and wage enrichment.
6. Company career pages for selected employers after legal review.

This order gives VeriBridge a reliable U.S. salary baseline first, then adds live opportunity signals.

## Open Questions Before API Integration

- Which countries should the first heatmap support?
- Which student role families need coverage first?
- Will the MVP compare internship hourly pay, entry-level annual salary, or both?
- What cache duration is acceptable for job postings?
- What provider terms apply to displaying snippets, company names, and apply links?
- Do providers allow derived analytics such as open role estimates?
- How should duplicate postings across aggregators be resolved?
- What evidence is required before showing work authorization fit?

## Recommendation

Use mock/static market data now and build the provider abstraction immediately. For real data, start with BLS/OEWS for U.S. salary and employment baselines, then add Adzuna or JSearch for live job-posting signals once API keys, quotas, and legal usage terms are confirmed.

The heatmap should remain student-centered: it should explain opportunity, market alignment, and compensation fit without treating students as cheaper substitutes for experienced workers.
