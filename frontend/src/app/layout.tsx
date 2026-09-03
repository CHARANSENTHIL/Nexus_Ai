import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Nexus AI — Autonomous Desktop Agent',
  description: 'Production-grade autonomous AI desktop agent dashboard. LangChain + CrewAI + Llama 3.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
