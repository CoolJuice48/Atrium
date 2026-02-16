import type { Metadata } from "next";
import "../styles/globals.css";
import { AuthProvider } from "./AuthContext";

export const metadata: Metadata = {
  title: "Atrium",
  description: "Textbook study platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
