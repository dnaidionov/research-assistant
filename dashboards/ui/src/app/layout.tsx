import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Research Assistant UI",
  description: "Manage research agent jobs and capabilities",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${outfit.variable} antialiased dark`}>
      <body className="min-h-screen flex flex-col font-sans selection:bg-brand-500/30 selection:text-brand-50">
        <div className="flex-1 flex flex-col items-center p-4 sm:p-8">
          <div className="w-full max-w-7xl relative mx-auto shadow-2xl h-full flex flex-col">
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
