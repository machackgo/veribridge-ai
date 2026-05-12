# Website Verification Guide Template

Use this template when submitting a deployed website or live web app as proof of a claimed skill. Write instructions that a reviewer or future VeriBridge browser agent can follow without guessing.

## Project Name

Example: Boston Accident Risk Rerouting Dashboard

## Live Website URL

Example: https://your-project.example.com

## GitHub URL (Optional)

Example: https://github.com/your-name/your-project

## Claimed Skills

Example: FastAPI, React, Google Cloud, SQL

## What The Website Does

Briefly explain the project, the user problem it solves, and your contribution.

## Feature To Verify

Name one concrete feature that demonstrates the claimed skill.

Example: The route risk form submits origin/destination data to a FastAPI backend and displays safer route recommendations.

## Exact Test Steps

1. Open the live website URL.
2. Navigate to the feature or page that should be tested.
3. Enter the sample inputs below.
4. Submit or run the feature.
5. Compare the page response to the expected output.

## Sample Inputs

Provide realistic values, test accounts, filters, form fields, or uploaded sample data.

Example:

```json
{
  "origin": "Boston Common",
  "destination": "Fenway Park",
  "travel_mode": "driving"
}
```

## Expected Output

Describe what should happen if the feature works correctly.

Example: The page displays two or more route options, each with an accident risk score, estimated duration, and a recommended safer route.

## Login Or Access Requirements

- Login required: yes/no
- Test account, if safe to share:
- Access notes:

Do not include private passwords or secrets. Use demo credentials only if they are intentionally public for review.

## Known Limitations

List expected cold starts, free-tier delays, disabled features, API quota limits, browser compatibility issues, or demo data constraints.

## Extra Notes

Add anything a reviewer or verification agent should know before testing.
