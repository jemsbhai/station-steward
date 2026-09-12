import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'Station Steward — agent workcell', description: 'Give a virtual station a goal. Watch an OpenAI agent choose tools, adapt to changes, and verify results within a Pollard budget.', icons: { icon: '/icon.svg' } };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
