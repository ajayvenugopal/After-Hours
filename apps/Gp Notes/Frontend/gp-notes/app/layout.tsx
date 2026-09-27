import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Gp Notes · A considered draft",
  description:
    "An open-source documentation lab. Explore a synthetic consultation, organize SOAP notes, and review before exporting.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to workspace
        </a>
        {children}
      </body>
    </html>
  );
}
