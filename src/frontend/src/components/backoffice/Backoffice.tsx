import { useState } from "react";
import { Queue } from "./Queue";
import { TaskDetail } from "./TaskDetail";

export function Backoffice() {
  const [selected, setSelected] = useState<number | null>(null);

  return selected === null ? (
    <Queue onOpen={setSelected} />
  ) : (
    <TaskDetail taskId={selected} onBack={() => setSelected(null)} />
  );
}
