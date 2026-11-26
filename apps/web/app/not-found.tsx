import Link from "next/link";

export default function NotFound() {
  return (
    <main className="cl-page" style={{ maxWidth: 560, margin: "89px auto", padding: "0 16px" }}>
      <h1 className="cl-title">That page does not exist</h1>
      <p className="cl-sub">The address may be old or mistyped.</p>
      <p><Link href="/">Go to the Overview</Link></p>
    </main>
  );
}
