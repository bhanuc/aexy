import { redirect } from "next/navigation";

interface Props {
  params: { agentId: string };
}

export default function CRMAgentDetailRedirect({ params }: Props) {
  redirect(`/agents/${params.agentId}`);
}
