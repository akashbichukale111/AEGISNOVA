import "./globals.css";
import type { Metadata } from "next";
import { Shell } from "../components/layout/Shell";

export const metadata: Metadata = {
  title: "AEGISNOVA — A New Standard for Safe AI",
  description:
    "Unified AI security, autonomous engineering, causal-impact analysis, repair-assurance, and UNWIND governance platform.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#070A10] text-slate-100 antialiased">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
