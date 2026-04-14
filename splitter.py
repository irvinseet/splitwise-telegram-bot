from collections import defaultdict


def parse_split(mode: str, total: float, split_map: dict[int, float | None]) -> dict[int, float]:
    member_ids = list(split_map.keys())
    if not member_ids:
        raise ValueError("No members selected for split")

    if mode == "equal":
        share = round(total / len(member_ids), 2)
        result = {mid: share for mid in member_ids}
        diff = round(total - sum(result.values()), 2)
        result[member_ids[0]] = round(result[member_ids[0]] + diff, 2)
        return result

    if mode == "exact":
        return {mid: round(float(v), 2) for mid, v in split_map.items()}

    if mode == "percent":
        result = {}
        for mid, pct in split_map.items():
            result[mid] = round(total * float(pct) / 100, 2)
        diff = round(total - sum(result.values()), 2)
        result[member_ids[0]] = round(result[member_ids[0]] + diff, 2)
        return result

    raise ValueError(f"Unknown mode: {mode}")


def simplify_debts(
    debts: dict[tuple[int, int], float],
    members: dict[int, str],
) -> list[tuple[str, str, float]]:
    net: dict[int, float] = defaultdict(float)

    for (debtor, creditor), amount in debts.items():
        net[debtor] -= amount
        net[creditor] += amount

    givers = sorted(
        [(mid, -bal) for mid, bal in net.items() if bal < -0.005],
        key=lambda x: -x[1],
    )
    receivers = sorted(
        [(mid, bal) for mid, bal in net.items() if bal > 0.005],
        key=lambda x: -x[1],
    )

    result = []
    gi = 0
    ri = 0
    givers = list(givers)
    receivers = list(receivers)

    while gi < len(givers) and ri < len(receivers):
        giver_id, give_amt = givers[gi]
        receiver_id, recv_amt = receivers[ri]

        transfer = round(min(give_amt, recv_amt), 2)
        result.append((
            members.get(giver_id, str(giver_id)),
            members.get(receiver_id, str(receiver_id)),
            transfer,
        ))

        givers[gi] = (giver_id, round(give_amt - transfer, 2))
        receivers[ri] = (receiver_id, round(recv_amt - transfer, 2))

        if givers[gi][1] < 0.005:
            gi += 1
        if receivers[ri][1] < 0.005:
            ri += 1

    return result


def format_balances(debts: dict[tuple[int, int], float], members: dict[int, str]) -> str:
    if not debts:
        return "🎉 All settled up! No outstanding balances."

    lines = ["💰 *Current balances:*\n"]
    for (debtor_id, creditor_id), amount in sorted(debts.items(), key=lambda x: -x[1]):
        debtor_name = members.get(debtor_id, str(debtor_id))
        creditor_name = members.get(creditor_id, str(creditor_id))
        lines.append(f"• {debtor_name} owes {creditor_name} *${amount:.2f}*")
    return "\n".join(lines)
