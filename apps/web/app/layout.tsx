import type { Metadata } from "next";
import type { ReactNode } from "react";
import { themeInitScript } from "@sendora/ui-kit";
import "@sendora/ui-kit/styles.css";
import "./globals.css";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = { title: "Pipecairn", description: "From first contact to a signed deal." };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-accent="clay" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
