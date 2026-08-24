import type { Metadata } from "next";
import { LandingV2 } from "../../components/landing-v2/LandingV2";
import "./landing-v2.css";

export const metadata: Metadata = {
  title: "VeriBridge AI — Don't just claim your skills. Prove them.",
  description:
    "VeriBridge AI turns real projects into a Verified Work Passport — published evidence recruiters can search, inspect, and act on. Evidence-based hiring infrastructure for candidates and recruiters.",
  openGraph: {
    title: "VeriBridge AI — Don't just claim your skills. Prove them.",
    description:
      "Real projects become a Verified Work Passport: GitHub code, live sites, documents, recorded project defenses. Recruiters search evidence, inspect proof, and save candidates.",
    url: "https://veribridgeai.com",
    siteName: "VeriBridge AI",
    images: [{ url: "/brand/social-avatar-1024.png", width: 1024, height: 1024 }],
  },
  twitter: {
    card: "summary",
    title: "VeriBridge AI — Don't just claim your skills. Prove them.",
    description:
      "Real projects become a Verified Work Passport. Recruiters search evidence, inspect proof, and save candidates.",
    images: ["/brand/social-avatar-1024.png"],
  },
};

export default function Home() {
  return <LandingV2 />;
}
