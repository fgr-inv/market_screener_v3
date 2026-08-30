
import json
import pandas as pd
import streamlit as st

from core.ui import hero, section_note
from core.model_governance import (
    load_registry,
    active_model,
    registry_frame,
    weight_frame,
    validate_weights,
    register_model,
)
from core.point_in_time import point_in_time_status

hero(
    "Model Governance",
    "Control, versionado y trazabilidad del modelo que genera los scores de la plataforma.",
    "Research Governance",
)

reg = load_registry()
model = active_model()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Active model", model.get("name", "Opportunity Model"))
c2.metric("Version", model.get("version", "N/A"))
c3.metric("Status", str(model.get("status", "production")).upper())
c4.metric("Effective date", model.get("effective_date", "N/A"))

st.subheader("Model weights")
section_note("Estos pesos determinan cuánto aporta cada factor al Opportunity Score. No son señales por sí solos.")

wf = weight_frame(model)
st.dataframe(
    wf[["Factor", "Weight %"]],
    use_container_width=True,
    hide_index=True,
)

validation = validate_weights(model.get("weights", {}))
if validation["valid"]:
    st.success(f"Weights validated · Total = {validation['total']:.0%}")
else:
    st.error(f"Invalid weights · Total = {validation['total']:.1%}")

st.subheader("Model history")
hist = registry_frame().sort_values("Updated", ascending=False)
st.dataframe(hist, use_container_width=True, hide_index=True)

st.subheader("Backtest integrity")
pit = point_in_time_status("SP500")
a, b = st.columns(2)
a.metric("Point-in-time constituents", "AVAILABLE" if pit.get("available") else "MISSING")
b.metric("Survivorship-bias control", "ENABLED" if pit.get("available") else "PARTIAL")

if not pit.get("available"):
    st.warning(
        "Los backtests que usan constituyentes actuales pueden tener survivorship bias. "
        "Cargá históricos point-in-time para validación institucional."
    )

with st.expander("Advanced change control"):
    st.caption(
        "Usá esta sección solo cuando quieras registrar una nueva versión del modelo. "
        "Los cambios quedan versionados para mantener comparabilidad histórica."
    )
    new_version = st.text_input("Nueva versión", model.get("version", ""))
    status = st.selectbox(
        "Estado",
        ["research", "candidate", "production", "retired"],
        index=2 if model.get("status", "production") == "production" else 0,
    )
    desc = st.text_input(
        "Descripción",
        model.get("description", model.get("notes", "")),
    )
    weights_df = wf[["Factor", "Weight"]].copy()
    edited = st.data_editor(
        weights_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Factor": st.column_config.TextColumn(disabled=True),
            "Weight": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.01, format="%.2f"),
        },
    )

    if st.button("Guardar nueva versión"):
        key_map = {
            str(k).replace("_", " ").title(): k
            for k in model.get("weights", {}).keys()
        }
        weights = {
            key_map[row["Factor"]]: float(row["Weight"])
            for _, row in edited.iterrows()
            if row["Factor"] in key_map
        }
        check = validate_weights(weights)
        if not check["valid"]:
            st.error(f"Los pesos deben sumar 100%. Actualmente suman {check['total']:.1%}.")
        else:
            register_model(
                new_version,
                status,
                desc,
                weights,
                notes="Updated from Model Governance UI",
            )
            st.success("Nueva versión registrada.")
            st.rerun()
