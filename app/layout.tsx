import "./globals.css";

export const metadata = {
  title: "ALOS — Second Mind",
  description: "Founder cognitive operating system"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
