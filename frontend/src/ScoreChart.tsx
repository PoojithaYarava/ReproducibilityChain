import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ScoreDatum = { reproduction_id: string; score: number };

export default function ScoreChart({ data }: { data: ScoreDatum[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid stroke="#243044" vertical={false} />
        <XAxis dataKey="reproduction_id" hide />
        <YAxis domain={[0, 100]} stroke="#8190a8" />
        <Tooltip
          contentStyle={{
            background: "#111a27",
            border: "1px solid #29384d",
            borderRadius: 10,
          }}
        />
        <Bar dataKey="score" fill="#61d6c6" radius={[5, 5, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
