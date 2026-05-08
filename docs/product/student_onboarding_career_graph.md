# Universal Student Onboarding + VeriBridge Career Graph

## Overview

Universal Student Onboarding captures the student context VeriBridge needs before recommending opportunities: academic background, career fields, target roles, skills, preferred locations, work modes, work authorization, timeline, and compensation expectations.

This onboarding flow must support all majors, career fields, and global locations. It is not limited to IT, CS, or AI students.

## VeriBridge Career Graph

The VeriBridge Career Graph is the structured profile generated from onboarding inputs and later evidence sources. It connects:

- Academic profile
- Career fields and target roles
- Skills and proof-of-skill evidence
- Target locations and work modes
- Work authorization constraints
- Compensation expectations
- Opportunity market signals

The graph becomes the foundation for job matching, recruiter discovery, university analytics, skill-gap analysis, and student-controlled visibility.

## Opportunity & Salary Heatmap

The Opportunity & Salary Heatmap compares a student's selected locations with recommended cities, regions, countries, and remote markets. Each location can show:

- Estimated open roles
- Estimated salary range
- Currency
- Competition level
- Remote availability
- Work authorization fit
- Salary/compensation fit
- Recommendation score
- Recommendation reasons

The goal is to help students decide whether to search only in their selected city or expand into stronger opportunity regions.

## Compensation Fit

Compensation Fit compares the student's expected and minimum acceptable compensation against market salary ranges. It should help students understand alignment with fair market ranges, role level, geography, and cost-sensitive decisions.

Ethical note: Compensation Fit must not rank students as "cheap" or encourage employers to target lower-cost candidates. It should show alignment with budget and fair market range while preserving student agency.

## MVP Market Data

The MVP uses sample/mock global market data only. It does not call paid APIs and does not require external API keys.

Current mock locations include:

- California, USA
- Massachusetts, USA
- New York, USA
- Toronto, Canada
- London, UK
- Dubai, UAE
- Hyderabad, India
- Sydney, Australia
- Remote worldwide

## Future Data Providers

The backend service is designed around a `MarketDataProvider` abstraction so real providers can be added later.

- Adzuna: job ads, regional vacancy data, salary data
- JSearch/RapidAPI: live job postings and salary info where available
- BLS: US wage data by occupation, metro, state, and national wage percentiles

Provider data must be normalized before it reaches the recommendation layer so the frontend can keep a stable response contract.
