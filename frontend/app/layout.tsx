import "./globals.css";

import { cn } from "@/lib/utils";
import { Montserrat } from "next/font/google";
import { AppShell } from "@/components/layout/AppShell";

const montserrat = Montserrat({ subsets: ["latin"] });

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      {/* <body className={cn(montserrat.className, "h-dvh")}> 
        {children}
      </body> */}
      <body className={cn(montserrat.className, "h-dvh")}> 
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
