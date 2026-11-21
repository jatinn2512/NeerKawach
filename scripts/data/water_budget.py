"""Volume accounting in m³. Percentages use the recorded input for that domain."""


def budget(input_m3, output_m3, initial_storage_m3, final_storage_m3):
    change = final_storage_m3 - initial_storage_m3
    residual = input_m3 - output_m3 - change
    return {"input_m3": input_m3, "output_m3": output_m3, "initial_storage_m3": initial_storage_m3,
            "final_storage_m3": final_storage_m3, "storage_change_m3": change, "residual_m3": residual,
            "residual_percent_of_input": 100 * residual / input_m3 if input_m3 else None}


def surface_budgets(states, initial_storage_m3):
    rows = []
    start = initial_storage_m3
    total_in = total_out = 0.0
    for state in states:
        refund = state.get("unused_capture_return_m3", 0.0)
        incoming = state["rainfall_input_m3"] + state.get("overflow_return_m3", 0.0) + refund
        outgoing = (state["coefficient_loss_m3"] + state["infiltration_loss_m3"]
                    + state["boundary_outflow_m3"] + state.get("surface_to_drainage_m3", 0.0))
        end = state["stored_surface_water_m3"]
        total_in += incoming
        total_out += outgoing
        rows.append({"timestamp": state["timestamp"], "rainfall_m3": state["rainfall_input_m3"],
                     "runoff_before_infiltration_m3": state["rainfall_input_m3"] - state["coefficient_loss_m3"],
                     "coefficient_loss_m3": state["coefficient_loss_m3"], "infiltration_m3": state["infiltration_loss_m3"],
                     "boundary_outflow_m3": state["boundary_outflow_m3"], "captured_m3": state.get("surface_to_drainage_m3", 0.0),
                     "returned_m3": state.get("overflow_return_m3", 0.0), "unused_capture_return_m3": refund,
                     "step": budget(incoming, outgoing, start, end),
                     "cumulative": budget(total_in, total_out, initial_storage_m3, end)})
        start = end
    return rows


def exchange_steps(states, node_rows, overflow_rows):
    """The volume removed at t supplies SWMM over (t, t+dt]."""
    from collections import defaultdict
    flux = defaultdict(lambda: [0.0, 0.0])
    for row in node_rows:
        values = flux[row["timestamp"]]
        values[0] += row["lateral_inflow_volume_m3"]
        values[1] += row["flooding_volume_m3"]
    unmapped = defaultdict(float)
    for row in overflow_rows:
        unmapped[row["timestamp"]] += row["unmapped_overflow_volume_m3"]
    samples = iter(sorted(flux.items()))
    item = next(samples, None)
    rows = []
    cumulative = [0.0] * 5
    for previous, current in zip(states, states[1:]):
        end = current["timestamp"]
        inflow = flooded = 0.0
        while item and item[0] <= end:
            inflow += item[1][0]
            flooded += item[1][1]
            item = next(samples, None)
        net_capture = (previous["surface_to_drainage_m3"] + previous["inlet_carry_m3"]
                       - current["inlet_carry_m3"] - current.get("unused_capture_return_m3", 0.0))
        values = [net_capture, inflow, flooded, current["overflow_return_m3"], unmapped[end]]
        cumulative = [a + b for a, b in zip(cumulative, values)]
        rows.append({"start": previous["timestamp"], "end": end, "step": exchange_budget(*values),
                     "cumulative": exchange_budget(*cumulative)})
    if item:
        raise ValueError("Hydraulic samples extend beyond the final surface state")
    return rows


def funded_rate(offered_m3, available_m3, previous_rate, window, max_step):
    """Reserve enough for SWMM's half-step transition, including a stop next window.

    With rate q, the greatest debit plus its outgoing half-step tail is
    q * window + max(previous_rate, q) * max_step / 2.
    """
    half = max_step / 2
    if available_m3 + 1e-9 < previous_rate * half:
        raise ValueError("Inlet reservation cannot fund the previous hydraulic rate")
    return max(0.0, min(offered_m3 / window, available_m3 / (window + half),
                        (available_m3 - previous_rate * half) / window))


def settle_inlet(balances, connections, admitted):
    """Consume a measured node admission from its contributing cell reservations."""
    total = sum(balances[key] for key in connections)
    if admitted < -1e-9 or admitted > total + 1e-9:
        raise ValueError("Measured SWMM admission is outside the funded inlet reservation")
    if total:
        fraction_left = max(0.0, 1.0 - admitted / total)
        for key in connections:
            balances[key] *= fraction_left


def exchange_budget(captured, sampled_inflow, sampled_flooding, applied_return, unmapped):
    # Keep both directions visible. Opposite discrepancies must not cancel.
    return {"capture": budget(captured, sampled_inflow, 0, 0),
            "overflow": budget(sampled_flooding, applied_return + unmapped, 0, 0)}
