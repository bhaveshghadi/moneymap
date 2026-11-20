import type { Metadata } from 'next';
import { Schibsted_Grotesk, Hanken_Grotesk, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';
import { THEME_BOOT, ThemeWatcher } from '@/ui/lib/theme';

// The design system type scale. next/font downloads the fonts at
// build time and serves them from this app — no runtime Google Fonts request.
const schibstedGrotesk = Schibsted_Grotesk({ subsets: ['latin'], display: 'swap', variable: '--nf-display' });
const hankenGrotesk = Hanken_Grotesk({ subsets: ['latin'], display: 'swap', variable: '--nf-text' });
const ibmPlexMono = IBM_Plex_Mono({ subsets: ['latin'], weight: '400', display: 'swap', variable: '--nf-mono' });

export const metadata: Metadata = {
  title: 'MoneyMap',
  description: 'Self-hosted personal expense tracker.',
  icons: { icon: '/assets/logo-icon.svg' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${schibstedGrotesk.variable} ${hankenGrotesk.variable} ${ibmPlexMono.variable}`} suppressHydrationWarning>
      <head>
        {/* light / dark before the first paint (Settings → Appearance) */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body suppressHydrationWarning>
        <ThemeWatcher />
        {children}
      </body>
    </html>
  );
}
