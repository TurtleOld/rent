import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Учёт платежей ЖКХ",
  description: "Трекер платежей за коммунальные услуги",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
