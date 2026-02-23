"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { register, ApiError } from "@/lib/api";
import styles from "../login/login.module.css";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await register(email, password);
      router.push("/login");
    } catch (err) {
      if (err instanceof ApiError && err.data) {
        const data = err.data as Record<string, string[]>;
        const firstMessage = Object.values(data).flat()[0];
        setError(firstMessage ?? "Ошибка регистрации.");
      } else {
        setError("Ошибка регистрации.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.container}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <h1 className={styles.title}>Регистрация</h1>
        {error && <p className={styles.error}>{error}</p>}
        <label className={styles.label}>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className={styles.input}
            autoComplete="email"
          />
        </label>
        <label className={styles.label}>
          Пароль (минимум 8 символов)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className={styles.input}
            autoComplete="new-password"
          />
        </label>
        <button type="submit" disabled={loading} className={styles.button}>
          {loading ? "Загрузка..." : "Зарегистрироваться"}
        </button>
        <a href="/login" className={styles.link}>
          Уже есть аккаунт? Войти
        </a>
      </form>
    </div>
  );
}
