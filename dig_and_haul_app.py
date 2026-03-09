"""
Dig and Haul Cost Calculator - Streamlit Web App v3.9
Run with: streamlit run dig_and_haul_app_v3.9.py

Version 2.0: Updated equipment productivity defaults to medium-class raw CY/hr midpoints;
             added full plain-text report export (assumptions + results) for AI chat use
Version 2.1-2.9: Various defaults, backfill %, report methodology, paid/productive hours,
             daily volume cap, truck logic fixes, trip rounding
Version 3.0: Standard trip rounding (.5+ up, .4- down)
Version 3.1: Major cost model restructure —
             - Equipment charged at daily rate (separate from operator)
             - Operators charged hourly with 1.5x OT on weekend days
             - Work days per week input (5/6/7, default 5)
             - Mob/Demob charge per unit, separate for excavators and loaders
             - Crew truck added (per-day charge, not billed on weather days)
             - Inclement weather days input (extends calendar, equipment still billed,
               operators and crew truck not billed)
             - Environmental Compliance & Insurance fee (% of equip+operators+crew truck)
             - Energy Surcharge (% of heavy equipment cost)
             - Environmental Consulting ($/CY)
             - Site Access Construction Contingency (flat $)
Version 3.2: Operator OT logic revised — OT now based on 40-hr weekly threshold
             rather than weekend-day detection. Added Operator Paid Hours/Day input
             (default 10, yard-to-yard). Partial weeks handled precisely: hours
             accumulate day by day within the partial week, OT kicks in after hr 40.
Version 3.3: No calculation changes — clarity update only. Improved sidebar help
             text and captions to explain the three-way hours split (productive hrs,
             operator paid hrs, daily equipment rate). Added live hours summary
             caption. Report Section 3 now has a dedicated "Three Types of Hours"
             block with worked examples.
Version 3.4: Updated default values to match project-specific inputs. Trucking
             cost model changed from trip-based to time-based — trucks contracted
             for the project are paid for all productive hours on site, so adding
             excess trucks now correctly increases cost. Truck utilization % added
             to Capacity tab and report.
Version 3.5: Fixed calendar days calculation — was incorrectly equal to working
             days (only added weather days). Now correctly accounts for weekends:
             Calendar Days = (Complete Weeks x 7) + Remaining Days + Weather Days.
Version 3.6: Trucking cost corrected — now uses operator_paid_hours_per_day (trucks
             operate in productive hours but are paid for full yard-to-yard day).
             Truck hourly rate default updated to $105. Crew & Site section renamed
             to Miscellaneous Equipment; added Porta Potty, Safety Trailer, and
             Dump Trailer as $/day inputs (default $0). EC&I base updated to
             include all misc equipment.
Version 3.7: Fixed circular truck utilization recommendation — was using
             floor(num_trucks × util%) which chased itself lower each time a
             truck was removed. Now uses ceil(excavation_CY/day /
             (trips_per_truck × truck_capacity)), stable and independent of
             current truck count.
Version 3.8: Mob/Demob inputs moved to Miscellaneous Equipment section; defaults
             lowered to $2,500/unit. Backfill at Landfill unchecked by default.
             Backfill travel field renamed to "Additional Travel Time for Backfill"
             to clarify it is additive to the standard round-trip cycle time.
"""

import streamlit as st
import pandas as pd
import math
import os
from pathlib import Path
from datetime import date

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dig and Haul Cost Calculator",
    page_icon="🚜",
    layout="wide"
)

st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 20px;
                   border-radius: 10px; margin: 10px 0; }
    </style>
    """, unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    logo_path = Path("Clean_Futures_2.png")
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown("<h2 style='text-align: center;'>Clean Futures</h2>",
                    unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>Dig and Haul Cost Calculator</h1>",
                unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Calculate costs and CO2 emissions for "
                "excavating contaminated soil and replacing with clean backfill</p>",
                unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray; font-size: 13px;'>"
                "Version 3.9</p>", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.header("📋 Project Inputs")

# Project Information
st.sidebar.subheader("Project Information")
total_volume = st.sidebar.number_input(
    "Total Volume to Excavate (CY)", min_value=1, value=87000, step=50)
backfill_pct = st.sidebar.number_input(
    "Backfill Volume (% of excavated)", min_value=0, max_value=100, value=100, step=5)
backfill_volume = total_volume * (backfill_pct / 100)
st.sidebar.caption(f"Backfill volume: {backfill_volume:,.0f} CY "
                   f"({backfill_pct}% of {total_volume:,} CY)")
productive_hours_per_day = st.sidebar.number_input(
    "Productive Hours per Day", min_value=1, value=8, step=1,
    help="Hours the equipment is actively running and moving soil. "
         "Drives: excavation volume/day, truck trips/day, and CO2 calculations. "
         "Typically less than paid hours due to yard travel, breaks, and inspections.")
operator_paid_hours_per_day = st.sidebar.number_input(
    "Operator Paid Hours per Day", min_value=1, value=10, step=1,
    help="Yard-to-yard hours — operators are paid from the time they leave the yard "
         "to the time they return. Typically longer than productive hours. "
         "Drives: operator cost and OT threshold only. Does NOT affect volume or truck trips.")
work_days_per_week = st.sidebar.selectbox(
    "Work Days per Week", options=[5, 6, 7], index=0,
    help="Number of days worked per week. OT is calculated on a 40-hr weekly threshold — "
         "any hours above 40 in a week are billed at 1.5x regardless of which day they fall on.")
st.sidebar.caption(
    f"📌 **Hours summary:** Equipment runs productively for {productive_hours_per_day} hrs/day "
    f"(volume & truck trips). Operators are paid for {operator_paid_hours_per_day} hrs/day "
    f"(yard-to-yard). Heavy equipment billed at a flat daily rate.")
weather_days = st.sidebar.number_input(
    "Inclement Weather Days", min_value=0, value=0, step=1,
    help="Days lost to weather. Equipment is still billed at daily rate. "
         "Operators and crew truck are NOT billed. Extends calendar duration.")

# Excavation Equipment
st.sidebar.subheader("Excavation Equipment")
num_excavators = st.sidebar.number_input(
    "Number of Excavators", min_value=0, value=1, step=1)
excavator_daily_rate = st.sidebar.number_input(
    "Excavator Daily Rate ($/day)", min_value=0, value=550, step=50,
    help="Bare equipment rental rate per day, including fuel. "
         "Billed for all project days AND weather days.")
excavator_operator_rate = st.sidebar.number_input(
    "Excavator Operator Rate ($/hr)", min_value=0, value=65, step=5,
    help="Operator hourly rate. 1.5x applied on weekend days if working 6 or 7 days/week.")
excavator_fuel = st.sidebar.number_input(
    "Excavator Fuel (gal/hr) — CO2 tracking", min_value=0.0, value=6.0, step=0.5)
excavator_capacity = st.sidebar.number_input(
    "Excavator Production (CY/hr)", min_value=0, value=105, step=5)

# Loader Equipment
st.sidebar.subheader("Loader Equipment")
num_loaders = st.sidebar.number_input(
    "Number of Loaders", min_value=0, value=1, step=1)
loader_daily_rate = st.sidebar.number_input(
    "Loader Daily Rate ($/day)", min_value=0, value=415, step=50,
    help="Bare equipment rental rate per day, including fuel. "
         "Billed for all project days AND weather days.")
loader_operator_rate = st.sidebar.number_input(
    "Loader Operator Rate ($/hr)", min_value=0, value=65, step=5,
    help="Operator hourly rate. 1.5x applied on weekend days if working 6 or 7 days/week.")
loader_fuel = st.sidebar.number_input(
    "Loader Fuel (gal/hr) — CO2 tracking", min_value=0.0, value=5.0, step=0.5)
loader_capacity = st.sidebar.number_input(
    "Loader Production (CY/hr)", min_value=0, value=130, step=5)

# Daily Volume Cap
max_volume_per_pair = st.sidebar.number_input(
    "Max Daily Volume per Equipment Pair (CY)",
    min_value=0, value=750, step=50,
    help="Real-world ceiling on daily excavation volume per excavator/loader pair.")
st.sidebar.caption("Accounts for logistics, inspections, operator breaks, truck queuing.")

# Trucking
st.sidebar.subheader("Trucking")
num_trucks = st.sidebar.number_input(
    "Number of Trucks", min_value=1, value=5, step=1)
truck_capacity = st.sidebar.number_input(
    "Truck Capacity (CY)", min_value=1, value=18, step=1)
truck_hourly_rate = st.sidebar.number_input(
    "Truck Hourly Rate ($/hr, includes driver & fuel)", min_value=0, value=105, step=5,
    help="Trucks operate (make trips) within productive hours, but are paid for the full "
         "operator paid hours/day. Cost = num trucks × paid hrs/day × rate × project days.")
truck_fuel_rate = st.sidebar.number_input(
    "Truck Fuel (gal/hr) — CO2 tracking", min_value=0.0, value=4.0, step=0.5)

# Miscellaneous Equipment (Daily Charges)
st.sidebar.subheader("Miscellaneous Equipment")
st.sidebar.caption("Daily items billed per working day. Not charged on weather days.")
num_crew_trucks = st.sidebar.number_input(
    "Number of Crew Trucks", min_value=0, value=1, step=1)
crew_truck_daily_rate = st.sidebar.number_input(
    "Crew Truck Daily Rate ($/day)", min_value=0, value=300, step=25,
    help="Billed on working days only — NOT billed on weather days.")
porta_potty_daily_rate = st.sidebar.number_input(
    "Porta Potty ($/day)", min_value=0, value=0, step=5,
    help="Daily rental charge for portable sanitation on site.")
safety_trailer_daily_rate = st.sidebar.number_input(
    "Safety Trailer ($/day)", min_value=0, value=0, step=25,
    help="Daily rental charge for on-site safety trailer.")
dump_trailer_daily_rate = st.sidebar.number_input(
    "Dump Trailer ($/day)", min_value=0, value=0, step=25,
    help="Daily rental charge for dump trailer, if needed.")
st.sidebar.caption("Mob/Demob — one-way charge per unit, assessed twice (mob + demob).")
excavator_mob_rate = st.sidebar.number_input(
    "Excavator Mob/Demob ($/unit)", min_value=0, value=2500, step=100,
    help="One-way charge per excavator. Assessed twice (mobilization + demobilization).")
loader_mob_rate = st.sidebar.number_input(
    "Loader Mob/Demob ($/unit)", min_value=0, value=2500, step=100,
    help="One-way charge per loader. Assessed twice (mobilization + demobilization).")

# Fees & Contingencies
st.sidebar.subheader("Fees & Contingencies")
eci_pct = st.sidebar.number_input(
    "Environmental Compliance & Insurance (%)", min_value=0.0, value=12.0, step=0.5,
    help="Applied as % of (heavy equipment + operators + crew truck).")
energy_surcharge_pct = st.sidebar.number_input(
    "Energy Surcharge (%)", min_value=0.0, value=28.0, step=0.5,
    help="Applied as % of heavy equipment cost only.")
env_consulting_rate = st.sidebar.number_input(
    "Environmental Consulting ($/CY)", min_value=0, value=3, step=1,
    help="Multiplied by total excavated volume.")
site_access_contingency = st.sidebar.number_input(
    "Site Access Construction Contingency ($)", min_value=0, value=0, step=500,
    help="Flat dollar amount for roadwork or access construction, if required.")

# Fuel Surcharge
st.sidebar.subheader("Fuel Surcharge (Optional)")
fuel_surcharge_enabled = st.sidebar.checkbox("Enable Fuel Surcharge", value=False)
if fuel_surcharge_enabled:
    fuel_surcharge_amount = st.sidebar.number_input(
        "Surcharge Amount ($)", min_value=0, value=250, step=50)
    fuel_surcharge_interval = st.sidebar.selectbox(
        "Surcharge Interval", ["daily", "weekly", "per-trip"])
else:
    fuel_surcharge_amount = 0
    fuel_surcharge_interval = "daily"

# Trip Times
st.sidebar.subheader("Trip Times")
loading_time = st.sidebar.number_input(
    "Loading Time (hours)", min_value=0.0, value=0.10, step=0.05)
travel_time = st.sidebar.number_input(
    "Travel to Landfill (hours, one-way)", min_value=0.0, value=0.5, step=0.1)
landfill_time = st.sidebar.number_input(
    "Time at Landfill (wait + dump, hours)", min_value=0.0, value=0.25, step=0.05)

# Backfill
st.sidebar.subheader("Backfill")
backfill_at_landfill = st.sidebar.checkbox("Backfill Available at Landfill", value=False)
backfill_cost = st.sidebar.number_input(
    "Backfill Cost ($/CY)", min_value=0, value=10, step=1)
if not backfill_at_landfill:
    travel_to_backfill = st.sidebar.number_input(
        "Additional Travel Time for Backfill (hours)", min_value=0.0, value=0.25, step=0.05,
        help="Extra time added to the round-trip cycle for backfill pickup. "
             "Added on top of the standard landfill round-trip time.")
    backfill_loading_time = st.sidebar.number_input(
        "Backfill Loading Time (hours)", min_value=0.0, value=0.10, step=0.05)
else:
    travel_to_backfill = 0
    backfill_loading_time = 0

# Disposal
st.sidebar.subheader("Disposal")
disposal_cost = st.sidebar.number_input(
    "Disposal Cost ($/CY)", min_value=0, value=25, step=1)

# Calculate button
calculate = st.sidebar.button("🧮 Calculate", type="primary")

# ── Calculations ──────────────────────────────────────────────────────────────
if calculate or 'results' in st.session_state:

    # ── Excavation capacity ──
    excavator_total_capacity = num_excavators * excavator_capacity
    loader_total_capacity    = num_loaders    * loader_capacity

    if excavator_total_capacity > 0 and loader_total_capacity > 0:
        excavation_capacity = min(excavator_total_capacity, loader_total_capacity)
        if   excavator_total_capacity < loader_total_capacity: equipment_bottleneck = "Excavator"
        elif loader_total_capacity < excavator_total_capacity: equipment_bottleneck = "Loader"
        else:                                                   equipment_bottleneck = "Balanced"
        num_pairs = min(num_excavators, num_loaders)
    elif excavator_total_capacity > 0:
        excavation_capacity  = excavator_total_capacity
        equipment_bottleneck = "N/A"
        num_pairs            = num_excavators
    else:
        excavation_capacity  = loader_total_capacity
        equipment_bottleneck = "N/A"
        num_pairs            = num_loaders

    excavation_volume_per_day_uncapped = excavation_capacity * productive_hours_per_day
    daily_volume_cap = (num_pairs * max_volume_per_pair
                        if max_volume_per_pair > 0
                        else excavation_volume_per_day_uncapped)
    excavation_volume_per_day = min(excavation_volume_per_day_uncapped, daily_volume_cap)
    volume_cap_active = excavation_volume_per_day < excavation_volume_per_day_uncapped

    # ── Trip time ──
    if backfill_at_landfill:
        trip_time = loading_time + travel_time + landfill_time + travel_time + loading_time
    else:
        trip_time = (loading_time + travel_time + landfill_time
                     + travel_to_backfill + backfill_loading_time
                     + travel_time + loading_time)

    # ── Trucking capacity (standard rounding) ──
    trips_per_truck_per_day_raw      = productive_hours_per_day / trip_time
    trips_per_truck_per_day          = math.floor(trips_per_truck_per_day_raw + 0.5)
    total_trips_per_day_theoretical_raw = trips_per_truck_per_day_raw * num_trucks
    total_trips_per_day_theoretical  = trips_per_truck_per_day * num_trucks
    truck_volume_per_day_theoretical = total_trips_per_day_theoretical * truck_capacity

    truck_volume_per_day      = min(truck_volume_per_day_theoretical, excavation_volume_per_day)
    effective_trips_per_day_raw = truck_volume_per_day / truck_capacity
    effective_trips_per_day   = math.floor(effective_trips_per_day_raw + 0.5)

    # ── Bottleneck & project duration ──
    limiting_volume = min(excavation_volume_per_day, truck_volume_per_day_theoretical)
    bottleneck = "Trucking" if truck_volume_per_day_theoretical <= excavation_volume_per_day else "Excavation"

    project_days    = math.ceil(total_volume / limiting_volume)
    # Calendar days = working days expanded to full weeks (including weekends) + weather days
    _complete_weeks  = project_days // work_days_per_week
    _remaining_days  = project_days  % work_days_per_week
    calendar_days   = _complete_weeks * 7 + _remaining_days + weather_days
    num_trips       = math.ceil(total_volume / truck_capacity)

    # ── Operator OT — 40-hr weekly threshold ──
    # Operators paid yard-to-yard (operator_paid_hours_per_day).
    # Any hours over 40 in a calendar week are OT at 1.5x, regardless of day.
    weekly_paid_hours      = operator_paid_hours_per_day * work_days_per_week
    regular_hours_per_week = min(40, weekly_paid_hours)
    ot_hours_per_week      = max(0, weekly_paid_hours - 40)

    # Split project into complete weeks + partial-week remainder
    complete_weeks = project_days // work_days_per_week
    remaining_days = project_days  % work_days_per_week

    # Partial week: hours accumulate; OT kicks in after hr 40
    partial_hours         = remaining_days * operator_paid_hours_per_day
    partial_regular_hours = min(40, partial_hours)
    partial_ot_hours      = max(0, partial_hours - 40)

    # Helper: total project cost for one operator at a given rate
    def operator_project_cost(rate):
        complete = complete_weeks * (
            regular_hours_per_week * rate +
            ot_hours_per_week      * rate * 1.5)
        partial  = (partial_regular_hours * rate +
                    partial_ot_hours      * rate * 1.5)
        return complete + partial

    # OT summary values for display / report
    total_operator_regular_hrs = (complete_weeks * regular_hours_per_week
                                  + partial_regular_hours)
    total_operator_ot_hrs      = (complete_weeks * ot_hours_per_week
                                  + partial_ot_hours)

    # ── Cost calculations ──

    # 1. Heavy equipment — daily rate × (project days + weather days)
    total_billed_equipment_days = project_days + weather_days
    excavator_equipment_cost = num_excavators * excavator_daily_rate * total_billed_equipment_days
    loader_equipment_cost    = num_loaders    * loader_daily_rate    * total_billed_equipment_days
    total_equipment_cost     = excavator_equipment_cost + loader_equipment_cost

    # 2. Mob/Demob — 2× per unit (mob + demob)
    excavator_mob_cost = num_excavators * excavator_mob_rate * 2
    loader_mob_cost    = num_loaders    * loader_mob_rate    * 2
    total_mob_cost     = excavator_mob_cost + loader_mob_cost

    # 3. Operators — 40-hr OT threshold; not paid on weather days
    excavator_operator_cost = num_excavators * operator_project_cost(excavator_operator_rate)
    loader_operator_cost    = num_loaders    * operator_project_cost(loader_operator_rate)
    total_operator_cost     = excavator_operator_cost + loader_operator_cost

    # 4. Misc equipment — daily × project_days only (not weather days)
    crew_truck_cost        = num_crew_trucks * crew_truck_daily_rate * project_days
    porta_potty_cost       = porta_potty_daily_rate * project_days
    safety_trailer_cost    = safety_trailer_daily_rate * project_days
    dump_trailer_cost      = dump_trailer_daily_rate * project_days
    total_misc_cost        = crew_truck_cost + porta_potty_cost + safety_trailer_cost + dump_trailer_cost

    # 5. Energy Surcharge — % of heavy equipment
    energy_surcharge_cost = (energy_surcharge_pct / 100) * total_equipment_cost

    # 6. Environmental Compliance & Insurance — % of (equipment + operators + misc equipment)
    eci_base = total_equipment_cost + total_operator_cost + total_misc_cost
    eci_cost = (eci_pct / 100) * eci_base

    # 7. Trucking — trucks are on-site and on the clock for the full productive day.
    #    Paying for num_trucks × hours on site × project days, regardless of whether
    #    they are running or waiting on excavation.
    #    num_trips is kept for disposal cost, fuel surcharge, and trip display.
    total_truck_hours = num_trips * trip_time   # kept for CO2 / surcharge / display
    # Trucks operate (make trips) within productive hours, but are paid for full paid hours/day
    trucking_cost = num_trucks * operator_paid_hours_per_day * truck_hourly_rate * project_days
    # Utilization: active trip hours vs. total contracted truck hours (productive only)
    active_truck_hours = effective_trips_per_day * trip_time * project_days
    total_contracted_truck_hours = num_trucks * operator_paid_hours_per_day * project_days
    truck_utilization_pct = (active_truck_hours / total_contracted_truck_hours * 100
                             if total_contracted_truck_hours > 0 else 0)

    # 8. Fuel Surcharge
    if fuel_surcharge_enabled:
        if   fuel_surcharge_interval == "daily":
            fuel_surcharge_cost = fuel_surcharge_amount * project_days
        elif fuel_surcharge_interval == "weekly":
            fuel_surcharge_cost = fuel_surcharge_amount * math.ceil(project_days / 7)
        elif fuel_surcharge_interval == "per-trip":
            fuel_surcharge_cost = fuel_surcharge_amount * num_trips
        else:
            fuel_surcharge_cost = 0
    else:
        fuel_surcharge_cost = 0

    # 9. Disposal & Backfill
    total_disposal_cost = total_volume  * disposal_cost
    total_backfill_cost = backfill_volume * backfill_cost

    # 10. Environmental Consulting
    env_consulting_cost = env_consulting_rate * total_volume

    # 11. Site Access Contingency (flat)
    # already a dollar value

    # ── Grand total ──
    total_cost = (
        total_equipment_cost +
        total_mob_cost +
        total_operator_cost +
        total_misc_cost +
        energy_surcharge_cost +
        eci_cost +
        trucking_cost +
        fuel_surcharge_cost +
        total_disposal_cost +
        total_backfill_cost +
        env_consulting_cost +
        site_access_contingency
    )
    cost_per_cy = total_cost / total_volume

    # ── CO2 (productive hours only) ──
    productive_project_hours = project_days * productive_hours_per_day
    total_fuel_gallons = (
        num_excavators * excavator_fuel * productive_project_hours +
        num_loaders    * loader_fuel    * productive_project_hours +
        total_truck_hours * truck_fuel_rate)
    co2_lbs  = total_fuel_gallons * 22.4
    co2_tons = co2_lbs / 2000

    # ── Store results ──
    st.session_state['results'] = {
        # Schedule
        'project_days':   project_days,
        'calendar_days':  calendar_days,
        'weather_days':   weather_days,
        'num_trips':      num_trips,
        'bottleneck':     bottleneck,
        # Capacity
        'excavator_capacity':               excavator_total_capacity,
        'loader_capacity':                  loader_total_capacity,
        'excavation_capacity':              excavation_capacity,
        'equipment_bottleneck':             equipment_bottleneck,
        'num_pairs':                        num_pairs,
        'excavation_volume_per_day_uncapped': excavation_volume_per_day_uncapped,
        'daily_volume_cap':                 daily_volume_cap,
        'volume_cap_active':                volume_cap_active,
        'excavation_volume_per_day':        excavation_volume_per_day,
        'truck_volume_per_day':             truck_volume_per_day,
        'truck_volume_per_day_theoretical': truck_volume_per_day_theoretical,
        'effective_trips_per_day':          effective_trips_per_day,
        'effective_trips_per_day_raw':      effective_trips_per_day_raw,
        'trips_per_truck_per_day':          trips_per_truck_per_day,
        'trips_per_truck_per_day_raw':      trips_per_truck_per_day_raw,
        'total_trips_per_day_theoretical':  total_trips_per_day_theoretical,
        'total_trips_per_day_theoretical_raw': total_trips_per_day_theoretical_raw,
        'trip_time':                        trip_time,
        # OT summary
        'weekly_paid_hours':         weekly_paid_hours,
        'regular_hours_per_week':    regular_hours_per_week,
        'ot_hours_per_week':         ot_hours_per_week,
        'complete_weeks':            complete_weeks,
        'remaining_days':            remaining_days,
        'total_operator_regular_hrs': total_operator_regular_hrs,
        'total_operator_ot_hrs':     total_operator_ot_hrs,
        # Costs
        'total_equipment_cost':     total_equipment_cost,
        'excavator_equipment_cost': excavator_equipment_cost,
        'loader_equipment_cost':    loader_equipment_cost,
        'total_mob_cost':           total_mob_cost,
        'excavator_mob_cost':       excavator_mob_cost,
        'loader_mob_cost':          loader_mob_cost,
        'total_operator_cost':      total_operator_cost,
        'excavator_operator_cost':  excavator_operator_cost,
        'loader_operator_cost':     loader_operator_cost,
        'crew_truck_cost':          crew_truck_cost,
        'porta_potty_cost':         porta_potty_cost,
        'safety_trailer_cost':      safety_trailer_cost,
        'dump_trailer_cost':        dump_trailer_cost,
        'total_misc_cost':          total_misc_cost,
        'energy_surcharge_cost':    energy_surcharge_cost,
        'eci_cost':                 eci_cost,
        'trucking_cost':            trucking_cost,
        'total_truck_hours':        total_truck_hours,
        'active_truck_hours':       active_truck_hours,
        'total_contracted_truck_hours': total_contracted_truck_hours,
        'truck_utilization_pct':    truck_utilization_pct,
        'fuel_surcharge_cost':      fuel_surcharge_cost,
        'total_disposal_cost':      total_disposal_cost,
        'total_backfill_cost':      total_backfill_cost,
        'env_consulting_cost':      env_consulting_cost,
        'site_access_contingency':  site_access_contingency,
        'total_cost':               total_cost,
        'cost_per_cy':              cost_per_cy,
        # CO2
        'total_fuel_gallons': total_fuel_gallons,
        'co2_tons':           co2_tons,
    }

    results = st.session_state['results']

    # ── Recalculate button ──
    recalc_col, _ = st.columns([1, 4])
    with recalc_col:
        st.button("🔄 Recalculate", type="primary", key="recalc_btn")

    # ── Results summary metrics ──
    st.header("📊 Results Summary")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Cost",    f"${results['total_cost']:,.0f}")
        st.metric("Cost per CY",   f"${results['cost_per_cy']:.2f}")
    with col2:
        st.metric("Working Days",  f"{results['project_days']} days")
        st.metric("Calendar Days", f"{results['calendar_days']} days"
                  + (f" (+{weather_days} weather)" if weather_days > 0 else ""))
    with col3:
        st.metric("CO2 Emissions", f"{results['co2_tons']:.2f} tons")
        st.metric("Truck Trips",   f"{results['num_trips']} trips")
    with col4:
        st.metric("Bottleneck",       results['bottleneck'])
        st.metric("Equipment Limit",  results['equipment_bottleneck'])

    # ── Detailed analysis tabs ──
    st.header("📈 Detailed Analysis")
    tab1, tab2, tab3 = st.tabs(
        ["💰 Cost Breakdown", "⚙️ Capacity Analysis", "🌍 Environmental Impact"])

    # ── Tab 1: Cost Breakdown ──
    with tab1:
        st.subheader("Cost Breakdown")
        col1, col2 = st.columns(2)

        with col1:
            cost_data = {
                'Category': [
                    'Heavy Equipment (daily)',
                    '  — Excavators',
                    '  — Loaders',
                    'Mob / Demob',
                    'Operators',
                    '  — Excavator Operators',
                    '  — Loader Operators',
                    'Misc Equipment',
                    '  — Crew Truck(s)',
                    '  — Porta Potty',
                    '  — Safety Trailer',
                    '  — Dump Trailer',
                    'Energy Surcharge',
                    'EC&I Fee',
                    'Trucking',
                    'Fuel Surcharge',
                    'Disposal',
                    'Backfill Material',
                    'Environmental Consulting',
                    'Site Access Contingency',
                ],
                'Cost': [
                    f"${results['total_equipment_cost']:,.0f}",
                    f"  ${results['excavator_equipment_cost']:,.0f}",
                    f"  ${results['loader_equipment_cost']:,.0f}",
                    f"${results['total_mob_cost']:,.0f}",
                    f"${results['total_operator_cost']:,.0f}",
                    f"  ${results['excavator_operator_cost']:,.0f}",
                    f"  ${results['loader_operator_cost']:,.0f}",
                    f"${results['total_misc_cost']:,.0f}",
                    f"  ${results['crew_truck_cost']:,.0f}",
                    f"  ${results['porta_potty_cost']:,.0f}",
                    f"  ${results['safety_trailer_cost']:,.0f}",
                    f"  ${results['dump_trailer_cost']:,.0f}",
                    f"${results['energy_surcharge_cost']:,.0f}",
                    f"${results['eci_cost']:,.0f}",
                    f"${results['trucking_cost']:,.0f}",
                    f"${results['fuel_surcharge_cost']:,.0f}",
                    f"${results['total_disposal_cost']:,.0f}",
                    f"${results['total_backfill_cost']:,.0f}",
                    f"${results['env_consulting_cost']:,.0f}",
                    f"${results['site_access_contingency']:,.0f}",
                ]
            }
            df_costs = pd.DataFrame(cost_data)
            st.dataframe(df_costs, hide_index=True, use_container_width=True)
            st.metric("**TOTAL**", f"${results['total_cost']:,.0f}")

            if weather_days > 0:
                st.info(f"⛈️ **Weather note:** Equipment billed for "
                        f"{project_days + weather_days} days "
                        f"({project_days} working + {weather_days} weather). "
                        f"Operators and misc equipment billed for {project_days} working days only.")
            if results['total_operator_ot_hrs'] > 0:
                ot_pct = results['total_operator_ot_hrs'] / (results['total_operator_regular_hrs'] + results['total_operator_ot_hrs']) * 100
                st.info(f"⏱️ **OT note:** {results['weekly_paid_hours']} hrs/week "
                        f"({operator_paid_hours_per_day} hrs/day × {work_days_per_week} days) "
                        f"exceeds 40-hr threshold by {results['ot_hours_per_week']:.0f} hrs/week. "
                        f"Project total: {results['total_operator_regular_hrs']:.0f} regular hrs + "
                        f"{results['total_operator_ot_hrs']:.0f} OT hrs "
                        f"({ot_pct:.0f}% of operator hours at 1.5x).")

        with col2:
            chart_cats = [
                'Equipment', 'Mob/Demob', 'Operators', 'Misc Equipment',
                'Energy Surcharge', 'EC&I', 'Trucking', 'Fuel Surcharge',
                'Disposal', 'Backfill', 'Env. Consulting', 'Site Access'
            ]
            chart_vals = [
                results['total_equipment_cost'], results['total_mob_cost'],
                results['total_operator_cost'],  results['total_misc_cost'],
                results['energy_surcharge_cost'],results['eci_cost'],
                results['trucking_cost'],        results['fuel_surcharge_cost'],
                results['total_disposal_cost'],  results['total_backfill_cost'],
                results['env_consulting_cost'],  results['site_access_contingency'],
            ]
            chart_data = pd.DataFrame({'Category': chart_cats, 'Cost': chart_vals})
            st.bar_chart(chart_data.set_index('Category'))

    # ── Tab 2: Capacity Analysis ──
    with tab2:
        st.subheader("Capacity Analysis")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Equipment Capacity**")
            capacity_data = {
                'Component': [
                    'Excavator Capacity',
                    'Loader Capacity',
                    'Excavation Capacity (bottleneck)',
                    'Equipment Bottleneck',
                    'Equipment Pairs',
                    'Productive Hours per Day',
                    'Theoretical Volume per Day',
                    'Daily Volume Cap (per pair)',
                    'Effective Excavation Volume/Day',
                    'Volume Cap Active?',
                ],
                'Value': [
                    f"{results['excavator_capacity']} CY/hr" if results['excavator_capacity'] > 0 else 'N/A',
                    f"{results['loader_capacity']} CY/hr"    if results['loader_capacity']    > 0 else 'N/A',
                    f"{results['excavation_capacity']} CY/hr",
                    results['equipment_bottleneck'],
                    f"{results['num_pairs']}",
                    f"{productive_hours_per_day} hrs",
                    f"{results['excavation_volume_per_day_uncapped']:.0f} CY",
                    f"{max_volume_per_pair} CY x {results['num_pairs']} pairs = "
                    f"{results['daily_volume_cap']:.0f} CY",
                    f"{results['excavation_volume_per_day']:.0f} CY",
                    "⚠️ Yes — cap is limiting" if results['volume_cap_active']
                    else "No — theoretical rate governs",
                ]
            }
            st.dataframe(pd.DataFrame(capacity_data), hide_index=True, use_container_width=True)

        with col2:
            st.markdown("**Trucking Capacity**")
            truck_data = {
                'Component': [
                    'Number of Trucks',
                    'Truck Capacity',
                    'Trip Time',
                    'Productive Hours per Day',
                    'Trips per Truck per Day',
                    'Total Trips per Day (theoretical)',
                    'Truck Volume per Day (theoretical)',
                    'Effective Trips per Day (excav-limited)',
                    'Effective Truck Volume per Day',
                ],
                'Value': [
                    f"{num_trucks}",
                    f"{truck_capacity} CY",
                    f"{results['trip_time']:.2f} hrs",
                    f"{productive_hours_per_day} hrs",
                    f"{results['trips_per_truck_per_day']} "
                    f"({results['trips_per_truck_per_day_raw']:.2f} actual)",
                    f"{results['total_trips_per_day_theoretical']} "
                    f"({results['total_trips_per_day_theoretical_raw']:.1f} actual)",
                    f"{results['truck_volume_per_day_theoretical']:.0f} CY",
                    f"{results['effective_trips_per_day']} "
                    f"({results['effective_trips_per_day_raw']:.1f} actual)"
                    if results['bottleneck'] == "Excavation"
                    else "N/A — trucking is bottleneck",
                    f"{results['truck_volume_per_day']:.0f} CY",
                ]
            }
            st.dataframe(pd.DataFrame(truck_data), hide_index=True, use_container_width=True)

        util = results['truck_utilization_pct']
        # Optimal trucks = how many trucks needed to keep pace with excavation output
        # Independent of current num_trucks — avoids circular recommendation
        optimal_trucks = math.ceil(excavation_volume_per_day / (trips_per_truck_per_day * truck_capacity)) if trips_per_truck_per_day > 0 else num_trucks
        util_note = (f"\n        - ✅ Trucks fully utilized ({util:.0f}% of productive hours on trips)"
                     if util >= 90
                     else f"\n        - ⚠️ Truck utilization: {util:.0f}% of productive hours on trips — "
                          f"excavation limits throughput to {results['excavation_volume_per_day']:.0f} CY/day. "
                          f"Optimal truck count: ~{optimal_trucks} trucks.")
        cap_note = (f"\n        - ⚠️ Volume cap active: theoretical "
                    f"{results['excavation_volume_per_day_uncapped']:.0f} CY/day "
                    f"capped at {results['daily_volume_cap']:.0f} CY/day"
                    if results['volume_cap_active'] else "")
        truck_note = (f"\n        - ⚠️ Trucks theoretical ({results['truck_volume_per_day_theoretical']:.0f} "
                      f"CY/day) exceeds excavation — limited to "
                      f"{results['truck_volume_per_day']:.0f} CY/day"
                      if results['bottleneck'] == 'Excavation'
                      and results['truck_volume_per_day_theoretical'] > results['excavation_volume_per_day']
                      else "")
        st.info(f"""
        **System Bottleneck: {results['bottleneck']}**

        - Excavation effective: {results['excavation_volume_per_day']:.0f} CY/day{cap_note}
        - Trucks theoretical:   {results['truck_volume_per_day_theoretical']:.0f} CY/day
        - Trucks effective:     {results['truck_volume_per_day']:.0f} CY/day{truck_note}{util_note}
        - Limiting factor:      {limiting_volume:.0f} CY/day
        - Productive hrs/day:   {productive_hours_per_day} hrs | Work days/week: {work_days_per_week}

        {"Consider adding more trucks to increase productivity."
         if results['bottleneck'] == 'Trucking'
         else "Excavation is limiting. Adding more trucks increases cost without increasing output."}
        """)

    # ── Tab 3: Environmental Impact ──
    with tab3:
        st.subheader("Environmental Impact")
        col1, col2 = st.columns(2)
        with col1:
            env_data = {
                'Metric': [
                    'Total Fuel Consumed',
                    'CO2 Emissions (lbs)',
                    'CO2 Emissions (tons)',
                    'CO2 per Cubic Yard',
                ],
                'Value': [
                    f"{results['total_fuel_gallons']:.0f} gallons",
                    f"{co2_lbs:,.0f} lbs",
                    f"{results['co2_tons']:.2f} tons",
                    f"{co2_lbs / total_volume:.2f} lbs/CY",
                ]
            }
            st.dataframe(pd.DataFrame(env_data), hide_index=True, use_container_width=True)
            st.caption("Fuel consumption uses productive hours only — "
                       "equipment is not running during yard transit or weather days.")
        with col2:
            st.metric("🌳 Equivalent Trees Needed", f"{int(results['co2_tons'] * 16.5):,}")
            st.caption("Trees needed to offset CO2 over 1 year (EPA estimate)")
            st.metric("🚗 Equivalent Car Miles", f"{int(results['co2_tons'] * 2500):,}")
            st.caption("Miles driven by average car (EPA estimate)")

    # ── Download Results ──
    st.header("💾 Download Results")

    # Build text report
    backfill_location_str = ("At landfill (no separate trip)"
                             if backfill_at_landfill else "Separate backfill site")
    backfill_trip_str     = ("N/A (backfill at landfill)" if backfill_at_landfill
                             else f"{travel_to_backfill:.2f} hrs additional travel + "
                                  f"{backfill_loading_time:.2f} hrs loading")
    surcharge_str         = (f"${fuel_surcharge_amount:,} {fuel_surcharge_interval}"
                             if fuel_surcharge_enabled else "Disabled")

    report_lines = [
        "=" * 65,
        "  DIG AND HAUL COST ESTIMATE REPORT",
        "  Clean Futures | Dig and Haul Cost Calculator v3.9",
        f"  Generated: {date.today().strftime('%B %d, %Y')}",
        "=" * 65,
        "",
        "--- SECTION 1: INPUT ASSUMPTIONS ---",
        "",
        "[ Project Parameters ]",
        f"  Total Volume to Excavate:         {total_volume:,} CY",
        f"  Backfill Volume:                  {backfill_volume:,.0f} CY ({backfill_pct}%)",
        f"  Productive Hours per Day:         {productive_hours_per_day} hrs",
        f"    → drives: excavation volume/day, truck trips/day, CO2",
        f"  Operator Paid Hours per Day:      {operator_paid_hours_per_day} hrs (yard-to-yard)",
        f"    → drives: operator cost and OT threshold only",
        f"  Heavy Equipment:                  flat daily rate (not hour-based)",
        f"  Work Days per Week:               {work_days_per_week} days",
        f"  Weekly Operator Hours:            {weekly_paid_hours} hrs "
        f"({regular_hours_per_week:.0f} regular + {ot_hours_per_week:.0f} OT)",
        f"  Inclement Weather Days:           {weather_days} days",
        "",
        "[ Excavation Equipment ]",
        f"  Number of Excavators:             {num_excavators}",
        f"  Excavator Daily Rate:             ${excavator_daily_rate:,}/day",
        f"  Excavator Operator Rate:          ${excavator_operator_rate}/hr",
        f"  Excavator Mob/Demob:              ${excavator_mob_rate:,}/unit (x2)",
        f"  Excavator Fuel:                   {excavator_fuel} gal/hr (CO2 only)",
        f"  Excavator Production:             {excavator_capacity} CY/hr",
        "",
        "[ Loader Equipment ]",
        f"  Number of Loaders:                {num_loaders}",
        f"  Loader Daily Rate:                ${loader_daily_rate:,}/day",
        f"  Loader Operator Rate:             ${loader_operator_rate}/hr",
        f"  Loader Mob/Demob:                 ${loader_mob_rate:,}/unit (x2)",
        f"  Loader Fuel:                      {loader_fuel} gal/hr (CO2 only)",
        f"  Loader Production:                {loader_capacity} CY/hr",
        "",
        "[ Equipment Productivity Constraints ]",
        f"  Equipment Pairs:                  {results['num_pairs']}",
        f"  Max Daily Volume per Pair:        {max_volume_per_pair} CY",
        f"  Total Daily Volume Cap:           {results['daily_volume_cap']:.0f} CY",
        f"  Theoretical Daily Volume:         {results['excavation_volume_per_day_uncapped']:.0f} CY",
        f"  Effective Daily Volume:           {results['excavation_volume_per_day']:.0f} CY",
        f"  Volume Cap Active:                {'Yes' if results['volume_cap_active'] else 'No'}",
        "",
        "[ Trucking ]",
        f"  Number of Trucks:                 {num_trucks}",
        f"  Truck Capacity:                   {truck_capacity} CY",
        f"  Truck Hourly Rate:                ${truck_hourly_rate}/hr (driver & fuel incl.)",
        f"  Truck Fuel:                       {truck_fuel_rate} gal/hr (CO2 only)",
        "",
        "[ Trip Times ]",
        f"  Loading Time:                     {loading_time:.2f} hrs",
        f"  Travel to Landfill (one-way):     {travel_time:.2f} hrs",
        f"  Time at Landfill:                 {landfill_time:.2f} hrs",
        f"  Full Round-Trip Cycle Time:       {results['trip_time']:.2f} hrs",
        "",
        "[ Miscellaneous Equipment ]",
        f"  Number of Crew Trucks:            {num_crew_trucks}",
        f"  Crew Truck Daily Rate:            ${crew_truck_daily_rate}/day",
        f"  Porta Potty:                      ${porta_potty_daily_rate}/day",
        f"  Safety Trailer:                   ${safety_trailer_daily_rate}/day",
        f"  Dump Trailer:                     ${dump_trailer_daily_rate}/day",
        f"  (All misc items billed on working days only — not on weather days)",
        "",
        "[ Fees & Contingencies ]",
        f"  Environmental Compliance & Ins.:  {eci_pct}% of equip + operators + misc equipment",
        f"  Energy Surcharge:                 {energy_surcharge_pct}% of heavy equipment",
        f"  Environmental Consulting:         ${env_consulting_rate}/CY",
        f"  Site Access Contingency:          ${site_access_contingency:,}",
        "",
        "[ Backfill ]",
        f"  Backfill Location:                {backfill_location_str}",
        f"  Backfill Cost:                    ${backfill_cost}/CY",
        f"  Backfill Additional Travel/Loading: {backfill_trip_str}",
        "",
        "[ Disposal ]",
        f"  Disposal Cost:                    ${disposal_cost}/CY",
        "",
        "[ Fuel Surcharge ]",
        f"  Fuel Surcharge:                   {surcharge_str}",
        "",
        "=" * 65,
        "--- SECTION 2: CALCULATED RESULTS ---",
        "",
        "[ Schedule ]",
        f"  Working Days:                     {results['project_days']} days",
        f"  Weather Days:                     {results['weather_days']} days",
        f"  Total Calendar Days:              {results['calendar_days']} days",
        f"  Complete Weeks:                   {results['complete_weeks']}",
        f"  Remaining Days (partial week):    {results['remaining_days']}",
        f"  Total Truck Trips:                {results['num_trips']:,} trips",
        f"  Trips per Truck per Day:          {results['trips_per_truck_per_day']} "
        f"({results['trips_per_truck_per_day_raw']:.2f} actual)",
        f"  Total Operator Regular Hrs:       {results['total_operator_regular_hrs']:.0f} hrs",
        f"  Total Operator OT Hrs:            {results['total_operator_ot_hrs']:.0f} hrs",
        "",
        "[ Capacity & Bottleneck ]",
        f"  Excavation Capacity (net):        {results['excavation_capacity']} CY/hr",
        f"  Equipment Bottleneck:             {results['equipment_bottleneck']}",
        f"  Effective Excavation Vol/Day:     {results['excavation_volume_per_day']:.0f} CY",
        f"  Effective Truck Vol/Day:          {results['truck_volume_per_day']:.0f} CY",
        f"  System Bottleneck:                {results['bottleneck']}",
        "",
        "[ Cost Breakdown ]",
        f"  Heavy Equipment (daily):          ${results['total_equipment_cost']:>12,.2f}",
        f"    Excavators ({num_excavators} x ${excavator_daily_rate}/day x "
        f"{total_billed_equipment_days} days): ${results['excavator_equipment_cost']:>10,.2f}",
        f"    Loaders    ({num_loaders} x ${loader_daily_rate}/day x "
        f"{total_billed_equipment_days} days): ${results['loader_equipment_cost']:>10,.2f}",
        f"  Mob/Demob:                        ${results['total_mob_cost']:>12,.2f}",
        f"    Excavators ({num_excavators} x ${excavator_mob_rate:,} x 2): "
        f"${results['excavator_mob_cost']:>10,.2f}",
        f"    Loaders    ({num_loaders} x ${loader_mob_rate:,} x 2): "
        f"${results['loader_mob_cost']:>10,.2f}",
        f"  Operators:                        ${results['total_operator_cost']:>12,.2f}",
        f"    Excavator operators:            ${results['excavator_operator_cost']:>12,.2f}",
        f"    Loader operators:               ${results['loader_operator_cost']:>12,.2f}",
        f"  Misc Equipment:                   ${results['total_misc_cost']:>12,.2f}",
        f"    Crew Truck(s):                  ${results['crew_truck_cost']:>12,.2f}",
        f"    Porta Potty:                    ${results['porta_potty_cost']:>12,.2f}",
        f"    Safety Trailer:                 ${results['safety_trailer_cost']:>12,.2f}",
        f"    Dump Trailer:                   ${results['dump_trailer_cost']:>12,.2f}",
        f"  Energy Surcharge ({energy_surcharge_pct}%):       "
        f"${results['energy_surcharge_cost']:>12,.2f}",
        f"  EC&I Fee ({eci_pct}%):                  ${results['eci_cost']:>12,.2f}",
        f"  Trucking ({num_trucks} trucks × {operator_paid_hours_per_day} paid hrs × "
        f"${truck_hourly_rate}/hr × {results['project_days']} days): "
        f"${results['trucking_cost']:>12,.2f}  [{results['truck_utilization_pct']:.0f}% trip utilization]",
        f"  Fuel Surcharge:                   ${results['fuel_surcharge_cost']:>12,.2f}",
        f"  Disposal:                         ${results['total_disposal_cost']:>12,.2f}",
        f"  Backfill Material:                ${results['total_backfill_cost']:>12,.2f}",
        f"  Environmental Consulting:         ${results['env_consulting_cost']:>12,.2f}",
        f"  Site Access Contingency:          ${results['site_access_contingency']:>12,.2f}",
        f"  {'─' * 45}",
        f"  TOTAL PROJECT COST:               ${results['total_cost']:>12,.2f}",
        f"  Cost per Cubic Yard:              ${results['cost_per_cy']:>12,.2f}",
        "",
        "[ Environmental Impact ]",
        f"  Total Fuel Consumed:              {results['total_fuel_gallons']:,.0f} gallons",
        f"  CO2 Emissions:                    {results['co2_tons']:.2f} tons",
        f"  Equivalent Trees to Offset:       {int(results['co2_tons'] * 16.5):,} (1-year)",
        f"  Equivalent Car Miles:             {int(results['co2_tons'] * 2500):,} miles",
        "",
        "=" * 65,
        "--- SECTION 3: HOW KEY METRICS WERE DERIVED ---",
        "=" * 65,
        "",
        "[ Three Types of Hours — What Each One Does ]",
        "  This calculator uses three distinct hour concepts. Mixing them up",
        "  leads to incorrect costs or unrealistic production estimates.",
        "",
        "  1. PRODUCTIVE HOURS/DAY (default: 8)",
        "     The time equipment is actively running and moving soil.",
        "     Drives: excavation volume per day, truck trips per day, CO2.",
        "     Does NOT drive operator cost or equipment cost.",
        "     Example: 8 productive hrs x 105 CY/hr excavator = 840 CY/day (before cap).",
        "     Example: 8 productive hrs / 1.1 hr cycle = ~7 truck trips/truck/day.",
        "",
        "  2. OPERATOR PAID HOURS/DAY (default: 10)",
        "     Yard-to-yard time — operators are on the clock from when they",
        "     leave the yard to when they return. Longer than productive hours",
        "     due to drive time, pre/post-trip inspections, and yard time.",
        "     Drives: operator cost and OT calculations ONLY.",
        "     Does NOT affect volume, truck trips, or equipment cost.",
        "     Example: 10 paid hrs x 5 days = 50 hrs/week → 10 OT hrs/week at 1.5x.",
        "",
        "  3. EQUIPMENT DAILY RATE",
        "     Heavy equipment (excavators, loaders) is billed at a flat rate",
        "     per day regardless of how many hours it runs. Billed for both",
        "     working days and weather days.",
        "     Does NOT depend on productive or paid hours at all.",
        "",
        f"  This project: {productive_hours_per_day} productive hrs | "
        f"{operator_paid_hours_per_day} operator paid hrs | "
        f"daily equipment rate",
        "",
        "[ Operator Overtime — 40-Hr Weekly Threshold ]",
        "  Operators are paid yard-to-yard, not just productive field hours.",
        "  Any hours worked beyond 40 in a calendar week are OT at 1.5x rate.",
        "  Weekly paid hrs = Operator Paid Hrs/Day × Work Days/Week",
        "  Regular hrs/week = MIN(40, weekly paid hrs)",
        "  OT hrs/week      = MAX(0, weekly paid hrs - 40)",
        "  Project is split into complete weeks + a partial-week remainder.",
        "  Partial week: hours accumulate day by day; OT kicks in after hr 40.",
        f"  This project: {operator_paid_hours_per_day} hrs/day × {work_days_per_week} days "
        f"= {weekly_paid_hours} hrs/week",
        f"  → {regular_hours_per_week:.0f} regular + {ot_hours_per_week:.0f} OT hrs/week",
        f"  {results['complete_weeks']} complete weeks + {results['remaining_days']} remaining days",
        f"  Partial week: {results['remaining_days']} days × {operator_paid_hours_per_day} hrs "
        f"= {partial_hours} hrs → {partial_regular_hours:.0f} reg + {partial_ot_hours:.0f} OT",
        f"  Project totals: {results['total_operator_regular_hrs']:.0f} regular hrs + "
        f"{results['total_operator_ot_hrs']:.0f} OT hrs",
        "",
        "[ Weather Days & Calendar Duration ]",
        "  Inclement weather days extend the calendar but do not add working days.",
        "  Equipment daily rate IS billed on weather days (equipment sits on site).",
        "  Operators are NOT paid on weather days.",
        "  Crew truck is NOT billed on weather days.",
        "  Calendar days account for both weekends and weather days:",
        "    Calendar Days = (Complete Weeks × 7) + Remaining Days + Weather Days",
        f"  This project: ({results['complete_weeks']} weeks × 7) + "
        f"{results['remaining_days']} days + {weather_days} weather = "
        f"{results['calendar_days']} calendar days",
        f"  Equipment billed for {total_billed_equipment_days} days total.",
        "",
        "[ Mob / Demob ]",
        "  Each piece of heavy equipment incurs a mobilization charge (delivery)",
        "  and a demobilization charge (pickup). Costs are assessed separately",
        "  for excavators and loaders, and billed at 2× the per-unit rate.",
        f"  Excavators: {num_excavators} units × ${excavator_mob_rate:,} × 2 = "
        f"${results['excavator_mob_cost']:,.2f}",
        f"  Loaders:    {num_loaders} units × ${loader_mob_rate:,} × 2 = "
        f"${results['loader_mob_cost']:,.2f}",
        "",
        "[ Energy Surcharge ]",
        f"  {energy_surcharge_pct}% applied to heavy equipment cost only.",
        f"  ${results['total_equipment_cost']:,.2f} × {energy_surcharge_pct}% = "
        f"${results['energy_surcharge_cost']:,.2f}",
        "",
        "[ Environmental Compliance & Insurance (EC&I) ]",
        f"  {eci_pct}% applied to the sum of heavy equipment + operators + misc equipment.",
        f"  Base: ${results['total_equipment_cost']:,.2f} + ${results['total_operator_cost']:,.2f} "
        f"+ ${results['total_misc_cost']:,.2f} = ${eci_base:,.2f}",
        f"  EC&I: ${eci_base:,.2f} × {eci_pct}% = ${results['eci_cost']:,.2f}",
        "",
        "[ Truck Cycle Time ]",
        "  Cycle Time = Loading + Travel to Landfill + Time at Landfill",
        "               + Return Travel + Loading (backfill trip)",
        f"  This project cycle time: {results['trip_time']:.2f} hrs",
        "",
        "[ Trucking Cost ]",
        "  Trucks operate (make trips) within productive hours only. However,",
        "  like equipment operators, truck drivers are paid for the full",
        "  yard-to-yard day (operator paid hours/day).",
        "  Cost = Num Trucks × Operator Paid Hrs/Day × Truck Hourly Rate × Project Days",
        "  Trip utilization % shows what fraction of productive hours are spent",
        "  actively on trips — trips happen in productive hours, pay covers paid hours.",
        f"  This project: {num_trucks} trucks × {operator_paid_hours_per_day} paid hrs × "
        f"${truck_hourly_rate}/hr × {results['project_days']} days = "
        f"${results['trucking_cost']:,.2f}",
        f"  Active trip hours (productive): {results['active_truck_hours']:.0f} hrs "
        f"({results['truck_utilization_pct']:.0f}% trip utilization of productive hours)",
        "",
        "[ Excavation Capacity & Daily Volume Cap ]",
        "  Net capacity = MIN(excavator CY/hr, loader CY/hr) × machine count",
        "  Theoretical daily = net capacity × productive hours",
        "  Cap = max_volume_per_pair × num_pairs",
        "  Effective = MIN(theoretical, cap)",
        f"  Effective: {results['excavation_volume_per_day']:.0f} CY/day "
        f"({'cap binding' if results['volume_cap_active'] else 'theoretical governs'})",
        "",
        "[ Project Duration ]",
        "  Working Days = CEILING(Total Volume / MIN(excavation, trucking) per day)",
        "  Calendar Days = (Complete Weeks × 7) + Remaining Days + Weather Days",
        "  Working days count only days the crew is on site.",
        "  Calendar days reflect the full elapsed duration including weekends and weather.",
        f"  CEILING({total_volume:,} / {limiting_volume:.0f}) = "
        f"{results['project_days']} working days",
        f"  ({results['complete_weeks']} × 7) + {results['remaining_days']} + "
        f"{weather_days} weather = {results['calendar_days']} calendar days",
        "",
        "[ CO2 Emissions ]",
        "  Uses productive hours only — equipment not burning fuel on weather/idle days.",
        "  Productive Project Hours = Working Days × Productive Hrs/Day",
        "  Total Fuel = (Excavators × gal/hr × productive hrs)",
        "             + (Loaders × gal/hr × productive hrs)",
        "             + (Total Truck Hours × truck gal/hr)",
        "  CO2 = Total Fuel × 22.4 lbs/gallon (EPA); tons = lbs / 2,000",
        f"  {results['total_fuel_gallons']:,.0f} gal × 22.4 = "
        f"{co2_lbs:,.0f} lbs = {results['co2_tons']:.2f} tons CO2",
        "",
        "=" * 65,
        "  NOTE: Equipment daily rates include fuel for the machine.",
        "  Fuel inputs are used for CO2 tracking only.",
        "=" * 65,
    ]

    report_text = "\n".join(report_lines)

    # ── Build Excel model with live formulas ──────────────────────────────────
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    def _xl_build(inputs):
        """Build the Excel financial model, populating inputs from current session."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Model"
        FONT_NAME = "Arial"
        BLUE = "0000FF"; BLACK = "000000"
        HEADER_BG = "1F4E79"; HEADER_FG = "FFFFFF"
        SUBHDR_BG = "D6E4F0"; RESULT_BG = "F0F7EE"; TOTAL_BG = "FFF2CC"

        def _fill(c): return PatternFill("solid", fgColor=c)
        def _font(bold=False, color=BLACK, size=10, italic=False):
            return Font(name=FONT_NAME, bold=bold, color=color, size=size, italic=italic)
        def _align(h="left", v="center"):
            return Alignment(horizontal=h, vertical=v)

        def _hdr(row, text, c1=1, c2=3, bg=HEADER_BG, fg=HEADER_FG, sz=11):
            ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
            c = ws.cell(row=row, column=c1, value=text)
            c.font = Font(name=FONT_NAME, bold=True, color=fg, size=sz)
            c.fill = _fill(bg); c.alignment = _align()

        def _sub(row, text, c1=1, c2=3, bg=SUBHDR_BG):
            ws.merge_cells(start_row=row, start_column=c1, end_row=row, end_column=c2)
            c = ws.cell(row=row, column=c1, value=text)
            c.font = _font(bold=True); c.fill = _fill(bg); c.alignment = _align()

        def _inp(row, label, value, unit=""):
            a = ws.cell(row=row, column=1, value=label)
            a.font = _font(); a.alignment = _align()
            b = ws.cell(row=row, column=2, value=value)
            b.font = _font(color=BLUE); b.alignment = _align("right")
            c = ws.cell(row=row, column=3, value=unit)
            c.font = _font(color="666666", size=9, italic=True); c.alignment = _align()
            return b

        def _calc(row, label, formula, unit="", bold=False, bg=None):
            e = ws.cell(row=row, column=5, value=label)
            e.font = _font(bold=bold); e.alignment = _align()
            f = ws.cell(row=row, column=6, value=formula)
            f.font = _font(bold=bold, color=BLACK); f.alignment = _align("right")
            g = ws.cell(row=row, column=7, value=unit)
            g.font = _font(color="666666", size=9, italic=True); g.alignment = _align()
            if bg:
                for col in [5, 6, 7]:
                    ws.cell(row=row, column=col).fill = _fill(bg)
            return f

        # Column widths
        for col, w in [("A",36),("B",16),("C",22),("D",2),("E",36),("F",16),("G",26)]:
            ws.column_dimensions[col].width = w

        # Title
        ws.row_dimensions[1].height = 30
        ws.merge_cells("A1:G1")
        t = ws["A1"]
        t.value = "Clean Futures  |  Dig & Haul Cost Model"
        t.font = Font(name=FONT_NAME, bold=True, size=16, color=HEADER_FG)
        t.fill = _fill("0D2137"); t.alignment = _align("center", "center")
        ws.row_dimensions[2].height = 14
        ws.merge_cells("A2:G2")
        sub = ws["A2"]
        sub.value = f"Generated: {date.today().strftime('%B %d, %Y')}    |    Blue = inputs (editable)    |    Black = formulas (do not edit)"
        sub.font = Font(name=FONT_NAME, size=9, italic=True, color="FFFFFF")
        sub.fill = _fill("1F4E79"); sub.alignment = _align("center", "center")
        ws.row_dimensions[3].height = 6

        # ── INPUTS ──────────────────────────────────────────────────────────
        _hdr(4, "  PROJECT PARAMETERS")
        _inp(5,  "Total Volume to Excavate",         inputs["total_volume"],              "CY")
        _inp(6,  "Backfill Volume (% of excavated)", inputs["backfill_pct"],              "%  (0-100)")
        _inp(7,  "Productive Hours per Day",         inputs["productive_hours_per_day"],  "hrs  (volume & trips)")
        _inp(8,  "Operator Paid Hours per Day",      inputs["operator_paid_hours_per_day"],"hrs  (yard-to-yard)")
        _inp(9,  "Work Days per Week",               inputs["work_days_per_week"],        "days  (5, 6, or 7)")
        _inp(10, "Inclement Weather Days",           inputs["weather_days"],              "days  (equip billed, ops not)")
        ws.row_dimensions[11].height = 6

        _hdr(12, "  EXCAVATION EQUIPMENT")
        _inp(13, "Number of Excavators",             inputs["num_excavators"],            "")
        _inp(14, "Excavator Daily Rate",             inputs["excavator_daily_rate"],      "$/day  (incl. fuel)")
        _inp(15, "Excavator Operator Rate",          inputs["excavator_operator_rate"],   "$/hr")
        _inp(16, "Excavator Production",             inputs["excavator_capacity"],        "CY/hr")
        _inp(17, "Excavator Fuel",                   inputs["excavator_fuel"],            "gal/hr  (CO2)")
        ws.row_dimensions[18].height = 6

        _hdr(19, "  LOADER EQUIPMENT")
        _inp(20, "Number of Loaders",                inputs["num_loaders"],               "")
        _inp(21, "Loader Daily Rate",                inputs["loader_daily_rate"],         "$/day  (incl. fuel)")
        _inp(22, "Loader Operator Rate",             inputs["loader_operator_rate"],      "$/hr")
        _inp(23, "Loader Production",                inputs["loader_capacity"],           "CY/hr")
        _inp(24, "Loader Fuel",                      inputs["loader_fuel"],               "gal/hr  (CO2)")
        _inp(25, "Max Daily Volume per Equip Pair",  inputs["max_volume_per_pair"],       "CY")
        ws.row_dimensions[26].height = 6

        _hdr(27, "  TRUCKING")
        _inp(28, "Number of Trucks",                 inputs["num_trucks"],                "")
        _inp(29, "Truck Capacity",                   inputs["truck_capacity"],            "CY")
        _inp(30, "Truck Hourly Rate",                inputs["truck_hourly_rate"],         "$/hr  (incl. driver & fuel)")
        _inp(31, "Truck Fuel",                       inputs["truck_fuel_rate"],           "gal/hr  (CO2)")
        ws.row_dimensions[32].height = 6

        _hdr(33, "  MISCELLANEOUS EQUIPMENT  (working days only)")
        _inp(34, "Number of Crew Trucks",            inputs["num_crew_trucks"],           "")
        _inp(35, "Crew Truck Daily Rate",            inputs["crew_truck_daily_rate"],     "$/day")
        _inp(36, "Porta Potty",                      inputs["porta_potty_daily_rate"],    "$/day")
        _inp(37, "Safety Trailer",                   inputs["safety_trailer_daily_rate"], "$/day")
        _inp(38, "Dump Trailer",                     inputs["dump_trailer_daily_rate"],   "$/day")
        _inp(39, "Excavator Mob/Demob",              inputs["excavator_mob_rate"],        "$/unit  (x2: mob+demob)")
        _inp(40, "Loader Mob/Demob",                 inputs["loader_mob_rate"],           "$/unit  (x2: mob+demob)")
        ws.row_dimensions[41].height = 6

        _hdr(42, "  FEES & CONTINGENCIES")
        b43 = _inp(43, "Environmental Compliance & Insurance", inputs["eci_pct"]/100,    "% of equip+ops+misc")
        b43.number_format = "0.0%"
        b44 = _inp(44, "Energy Surcharge",           inputs["energy_surcharge_pct"]/100, "% of heavy equipment")
        b44.number_format = "0.0%"
        _inp(45, "Environmental Consulting",         inputs["env_consulting_rate"],       "$/CY")
        _inp(46, "Site Access Contingency",          inputs["site_access_contingency"],   "$  (flat amount)")
        ws.row_dimensions[47].height = 6

        _hdr(48, "  TRIP TIMES")
        _inp(49, "Loading Time",                     inputs["loading_time"],              "hrs")
        _inp(50, "Travel to Landfill (one-way)",     inputs["travel_time"],               "hrs")
        _inp(51, "Time at Landfill (wait + dump)",   inputs["landfill_time"],             "hrs")
        _inp(52, "Backfill Available at Landfill",   1 if inputs["backfill_at_landfill"] else 0, "1=Yes  0=No")
        _inp(53, "Additional Travel Time for Backfill", inputs["travel_to_backfill"],    "hrs  (added to round-trip)")
        _inp(54, "Backfill Loading Time",            inputs["backfill_loading_time"],     "hrs")
        ws.row_dimensions[55].height = 6

        _hdr(56, "  BACKFILL & DISPOSAL")
        _inp(57, "Backfill Cost",                    inputs["backfill_cost"],             "$/CY")
        _inp(58, "Disposal Cost",                    inputs["disposal_cost"],             "$/CY")
        ws.row_dimensions[59].height = 6

        _hdr(60, "  FUEL SURCHARGE  (optional)")
        _inp(61, "Enable Fuel Surcharge",            1 if inputs["fuel_surcharge_enabled"] else 0, "1=Yes  0=No")
        _inp(62, "Surcharge Amount",                 inputs["fuel_surcharge_amount"],     "$")
        _inp(63, "Surcharge Interval",               inputs["fuel_surcharge_interval"],   "daily / weekly / per-trip")

        # ── CALCULATIONS (right side) ────────────────────────────────────────
        _hdr(4, "  SCHEDULE & CAPACITY", 5, 7)
        _calc(5,  "Round-Trip Cycle Time",           "=2*B49+2*B50+B51+IF(B52=0,B53+B54,0)", "hrs")
        _calc(6,  "Excavator Total Capacity",        "=B13*B16",  "CY/hr")
        _calc(7,  "Loader Total Capacity",           "=B20*B23",  "CY/hr")
        _calc(8,  "Excavation Capacity (net)",
            "=IF(AND(B13>0,B20>0),MIN(B13*B16,B20*B23),IF(B13>0,B13*B16,B20*B23))", "CY/hr")
        _calc(9,  "Equipment Pairs",
            "=IF(AND(B13>0,B20>0),MIN(B13,B20),IF(B13>0,B13,B20))", "")
        _calc(10, "Theoretical Excavation Vol/Day",  "=F8*B7",    "CY")
        _calc(11, "Daily Volume Cap (all pairs)",    "=F9*B25",   "CY")
        _calc(12, "Effective Excavation Vol/Day",    "=MIN(F10,F11)", "CY")
        _calc(13, "Trips per Truck per Day",         "=ROUND(B7/F5,0)", "trips")
        _calc(14, "Truck Vol/Day (theoretical)",     "=F13*B28*B29", "CY")
        _calc(15, "Effective Truck Vol/Day",         "=MIN(F14,F12)", "CY")
        _calc(16, "System Bottleneck",               '=IF(F14<=F12,"Trucking","Excavation")', "")
        _calc(17, "Limiting Volume/Day",             "=MIN(F12,F14)", "CY")
        _calc(18, "Optimal Truck Count",
            "=IFERROR(CEILING(F12/(F13*B29),1),B28)", "trucks")
        ws.row_dimensions[19].height = 6
        _sub(20, "  Project Duration", 5, 7)
        _calc(21, "Project Working Days",            "=CEILING(B5/F17,1)", "days", bold=True, bg=RESULT_BG)
        _calc(22, "Complete Weeks",                  "=INT(F21/B9)",        "weeks")
        _calc(23, "Remaining Days (partial week)",   "=MOD(F21,B9)",        "days")
        _calc(24, "Calendar Days (incl. wknds + wx)","=F22*7+F23+B10",      "days", bold=True, bg=RESULT_BG)
        _calc(25, "Equipment Billing Days",          "=F21+B10",            "days  (working + weather)")
        _calc(26, "Total Truck Trips",               "=CEILING(B5/B29,1)",  "trips")
        _calc(27, "Backfill Volume",                 "=B5*(B6/100)",        "CY")
        ws.row_dimensions[28].height = 6
        _sub(29, "  Operator OT  (40-hr weekly threshold)", 5, 7)
        _calc(30, "Weekly Paid Hours",               "=B8*B9",              "hrs/week")
        _calc(31, "Regular Hrs per Week",            "=MIN(40,F30)",        "hrs")
        _calc(32, "OT Hrs per Week",                 "=MAX(0,F30-40)",      "hrs  (at 1.5x)")
        _calc(33, "Partial Week Hours",              "=F23*B8",             "hrs")
        _calc(34, "Partial Week Regular Hrs",        "=MIN(40,F33)",        "hrs")
        _calc(35, "Partial Week OT Hrs",             "=MAX(0,F33-40)",      "hrs  (at 1.5x)")
        _calc(36, "Total Regular Hrs (per operator)","=F22*F31+F34",        "hrs")
        _calc(37, "Total OT Hrs (per operator)",     "=F22*F32+F35",        "hrs")
        ws.row_dimensions[38].height = 6

        _hdr(39, "  COST BREAKDOWN", 5, 7)
        _sub(40, "  Heavy Equipment  (daily rate x billing days)", 5, 7)
        _calc(41, "  Excavator Equipment",           "=B13*B14*F25",        "$")
        _calc(42, "  Loader Equipment",              "=B20*B21*F25",        "$")
        _calc(43, "  Total Heavy Equipment",         "=F41+F42",            "$", bold=True, bg=TOTAL_BG)
        _sub(44, "  Mob / Demob  (per unit x 2)", 5, 7)
        _calc(45, "  Excavator Mob/Demob",           "=B13*B39*2",          "$")
        _calc(46, "  Loader Mob/Demob",              "=B20*B40*2",          "$")
        _calc(47, "  Total Mob/Demob",               "=F45+F46",            "$", bold=True, bg=TOTAL_BG)
        _sub(48, "  Operators  (hourly + 1.5x OT above 40 hrs/wk)", 5, 7)
        _calc(49, "  Excavator Operators",           "=B13*(F36*B15+F37*B15*1.5)", "$")
        _calc(50, "  Loader Operators",              "=B20*(F36*B22+F37*B22*1.5)", "$")
        _calc(51, "  Total Operators",               "=F49+F50",            "$", bold=True, bg=TOTAL_BG)
        _sub(52, "  Misc Equipment  (working days only)", 5, 7)
        _calc(53, "  Crew Truck(s)",                 "=B34*B35*F21",        "$")
        _calc(54, "  Porta Potty",                   "=B36*F21",            "$")
        _calc(55, "  Safety Trailer",                "=B37*F21",            "$")
        _calc(56, "  Dump Trailer",                  "=B38*F21",            "$")
        _calc(57, "  Total Misc Equipment",          "=F53+F54+F55+F56",    "$", bold=True, bg=TOTAL_BG)
        ws.row_dimensions[58].height = 6
        _calc(59, "Energy Surcharge",                "=B44*F43",            "$")
        _calc(60, "EC&I Base  (equip + ops + misc)", "=F43+F51+F57",        "$")
        _calc(61, "EC&I Fee",                        "=B43*F60",            "$")
        ws.row_dimensions[62].height = 6
        _sub(63, "  Trucking  (paid hrs/day x rate x working days)", 5, 7)
        _calc(64, "  Trucking Cost",                 "=B28*B8*B30*F21",     "$", bold=True, bg=TOTAL_BG)
        _calc(65, "  Trip Utilization %",
            "=IFERROR(ROUND(F15/B29,0)*F5*F21/(B28*B8*F21),0)", "%")
        ws.row_dimensions[66].height = 6
        _calc(67, "Fuel Surcharge",
            '=IF(B61=0,0,IF(B63="daily",B62*F21,IF(B63="weekly",B62*CEILING(F21/7,1),IF(B63="per-trip",B62*F26,0))))',
            "$")
        ws.row_dimensions[68].height = 6
        _calc(69, "Disposal Cost",                   "=B5*B58",             "$")
        _calc(70, "Backfill Material Cost",          "=F27*B57",            "$")
        _calc(71, "Environmental Consulting",        "=B5*B45",             "$")
        _calc(72, "Site Access Contingency",         "=B46",                "$")
        ws.row_dimensions[73].height = 6

        # Grand Total row
        for col in [5, 6, 7]:
            ws.cell(row=74, column=col).fill = _fill(TOTAL_BG)
        ws.cell(row=74, column=5, value="TOTAL PROJECT COST").font = Font(name=FONT_NAME, bold=True, size=12)
        ws.cell(row=74, column=5).alignment = _align()
        tf = ws.cell(row=74, column=6, value="=F43+F47+F51+F57+F59+F61+F64+F67+F69+F70+F71+F72")
        tf.font = Font(name=FONT_NAME, bold=True, size=12, color=BLACK)
        tf.number_format = '$#,##0'; tf.alignment = _align("right")
        _calc(75, "Cost per Cubic Yard",             "=F74/B5",             "$/CY", bold=True, bg=TOTAL_BG)
        ws.row_dimensions[76].height = 6

        _hdr(77, "  ENVIRONMENTAL IMPACT", 5, 7, bg="2E7D32")
        _calc(78, "Productive Project Hours",        "=F21*B7",             "hrs")
        _calc(79, "Total Truck Hours (CO2)",         "=F26*F5",             "hrs")
        _calc(80, "Equipment Fuel",                  "=(B13*B17+B20*B24)*F78", "gallons")
        _calc(81, "Truck Fuel",                      "=F79*B31",            "gallons")
        _calc(82, "Total Fuel Consumed",             "=F80+F81",            "gallons", bold=True)
        _calc(83, "CO2 Emissions (lbs)",             "=F82*22.4",           "lbs  (EPA)")
        _calc(84, "CO2 Emissions (tons)",            "=F83/2000",           "tons", bold=True)
        _calc(85, "Equivalent Trees to Offset",      "=INT(F84*16.5)",      "trees  (1 yr, EPA)")
        _calc(86, "Equivalent Car Miles",            "=INT(F84*2500)",      "miles  (avg car)")

        # Number formats
        for r in [41,42,43,45,46,47,49,50,51,53,54,55,56,57,59,60,61,64,67,69,70,71,72,74,75]:
            ws.cell(row=r, column=6).number_format = '$#,##0;($#,##0);"-"'
        ws.cell(row=65, column=6).number_format = "0.0%"
        ws.cell(row=74, column=6).number_format = '$#,##0'
        ws.cell(row=75, column=6).number_format = '$#,##0.00'
        for r in [5,10,11,12,13,14,15,17]:
            ws.cell(row=r, column=6).number_format = '0.00'
        for r in [21,22,23,24,25,26,27,30,31,32,33,34,35,36,37,78,79,80,81,82,83,85,86]:
            ws.cell(row=r, column=6).number_format = '#,##0'
        ws.cell(row=84, column=6).number_format = '0.00'
        ws.cell(row=18, column=6).number_format = '0'
        ws.cell(row=5,  column=2).number_format = '#,##0'
        for r in [14,21,30,35,45,46,57,58,62]:
            ws.cell(row=r, column=2).number_format = '$#,##0'

        ws.freeze_panes = "A3"

        # Legend
        ws.row_dimensions[88].height = 6
        _hdr(89, "  COLOR KEY", 1, 7, bg="37474F", sz=10)
        legend_rows = [
            (90, "BLUE TEXT",    "Input cells — change these to model different scenarios", BLUE),
            (91, "BLACK TEXT",   "Formula cells — calculated automatically, do not edit", BLACK),
            (92, "YELLOW ROWS",  "Key totals and summary outputs", BLACK),
            (93, "OT Logic",     "Operators earn 1.5x for any hours over 40/week (yard-to-yard pay)", BLACK),
            (94, "Trucking Pay", "Trucks billed at paid hrs/day; trips happen within productive hrs only", BLACK),
            (95, "Equipment",    "Heavy equipment billed for ALL days incl. weather; operators NOT billed on weather days", BLACK),
            (96, "Backfill",     "When Backfill at Landfill = 0, additional travel + loading time added to cycle", BLACK),
        ]
        for row, key, desc, color in legend_rows:
            k = ws.cell(row=row, column=1, value=key)
            k.font = Font(name=FONT_NAME, bold=True, color=color, size=9)
            d = ws.cell(row=row, column=2, value=desc)
            d.font = Font(name=FONT_NAME, size=9, color="333333")
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
            ws.row_dimensions[row].height = 14

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.getvalue()

    xl_inputs = {
        "total_volume": total_volume, "backfill_pct": backfill_pct,
        "productive_hours_per_day": productive_hours_per_day,
        "operator_paid_hours_per_day": operator_paid_hours_per_day,
        "work_days_per_week": work_days_per_week, "weather_days": weather_days,
        "num_excavators": num_excavators, "excavator_daily_rate": excavator_daily_rate,
        "excavator_operator_rate": excavator_operator_rate,
        "excavator_capacity": excavator_capacity, "excavator_fuel": excavator_fuel,
        "num_loaders": num_loaders, "loader_daily_rate": loader_daily_rate,
        "loader_operator_rate": loader_operator_rate,
        "loader_capacity": loader_capacity, "loader_fuel": loader_fuel,
        "max_volume_per_pair": max_volume_per_pair,
        "num_trucks": num_trucks, "truck_capacity": truck_capacity,
        "truck_hourly_rate": truck_hourly_rate, "truck_fuel_rate": truck_fuel_rate,
        "num_crew_trucks": num_crew_trucks,
        "crew_truck_daily_rate": crew_truck_daily_rate,
        "porta_potty_daily_rate": porta_potty_daily_rate,
        "safety_trailer_daily_rate": safety_trailer_daily_rate,
        "dump_trailer_daily_rate": dump_trailer_daily_rate,
        "excavator_mob_rate": excavator_mob_rate, "loader_mob_rate": loader_mob_rate,
        "eci_pct": eci_pct, "energy_surcharge_pct": energy_surcharge_pct,
        "env_consulting_rate": env_consulting_rate,
        "site_access_contingency": site_access_contingency,
        "loading_time": loading_time, "travel_time": travel_time,
        "landfill_time": landfill_time, "backfill_at_landfill": backfill_at_landfill,
        "travel_to_backfill": travel_to_backfill,
        "backfill_loading_time": backfill_loading_time,
        "backfill_cost": backfill_cost, "disposal_cost": disposal_cost,
        "fuel_surcharge_enabled": fuel_surcharge_enabled,
        "fuel_surcharge_amount": fuel_surcharge_amount,
        "fuel_surcharge_interval": fuel_surcharge_interval,
    }
    xl_bytes = _xl_build(xl_inputs)

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            label="📄 Download Full Report (.txt)",
            data=report_text,
            file_name="dig_and_haul_report.txt",
            mime="text/plain",
            help="All assumptions + results — paste into AI chat for estimating assistance")
        st.caption("Includes full methodology. Ideal for AI chat prompts.")
    with dl_col2:
        st.download_button(
            label="📊 Download Excel Model (.xlsx)",
            data=xl_bytes,
            file_name="dig_and_haul_model.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Live Excel model with formulas — change any blue cell to recalculate.")

# ── Welcome screen ────────────────────────────────────────────────────────────
else:
    st.info("👈 Enter your project parameters in the sidebar and click **Calculate**")
    st.markdown("""
    ### How to Use This Calculator

    1. **Project info** — volume, productive hours, work days/week, weather days
    2. **Equipment** — excavators and loaders with daily rates, operator rates, mob/demob
    3. **Trucking** — number of trucks, capacity, hourly rate, trip times
    4. **Crew & Site** — crew truck count and daily rate
    5. **Fees** — EC&I %, Energy Surcharge %, Environmental Consulting $/CY, contingency
    6. **Backfill & Disposal** — costs per CY
    7. **Click Calculate**

    ### What You'll Get
    - Total project cost and cost per CY
    - Working days vs. calendar days (with weather)
    - Full cost breakdown across all 12 cost categories
    - Bottleneck analysis (excavation vs. trucking)
    - CO2 emissions tracking
    - Downloadable .txt report and .csv summary

    ### Version 3.1 Updates

    ✅ **Equipment charged daily** — separate daily rate for excavators and loaders  
    ✅ **Operators charged hourly** — separate $/hr rate per machine type  
    ✅ **Weekend OT** — 1.5x operator rate on Sat/Sun when working 6 or 7 day weeks  
    ✅ **Mob/Demob** — per-unit charge assessed 2x (mob + demob), separate by type  
    ✅ **Crew truck** — daily charge, not billed on weather days  
    ✅ **Weather days** — extends calendar; equipment still billed, operators/crew not  
    ✅ **Energy Surcharge** — % of heavy equipment cost  
    ✅ **EC&I fee** — % of equipment + operators + crew truck  
    ✅ **Environmental Consulting** — $/CY × total volume  
    ✅ **Site Access Contingency** — flat dollar amount  

    ### Version 3.2 Updates

    ✅ **Operator OT revised** — now based on 40-hr weekly threshold (not weekend detection)  
    ✅ **Operator Paid Hours/Day** — new input (default 10 hrs, yard-to-yard) drives OT math  
    ✅ **Partial week handling** — remaining days at end of project accumulate hours precisely;  
       OT kicks in after the 40th hour within that partial week  
    ✅ **OT always applies** — at 10 hrs/day × 5 days = 50 hrs/week, every week has 10 OT hrs  

    ### Version 3.3 Updates

    ✅ **Hours clarity** — sidebar labels and help text now explicitly explain the  
       three-way split: productive hrs (volume/trips/CO2), operator paid hrs  
       (cost/OT), and daily equipment rate (flat, not hour-based)  
    ✅ **Hours summary caption** — live reminder shown below the hours inputs  
       confirming which value drives which calculation  
    ✅ **Report methodology updated** — Section 3 now has a dedicated "Three Types  
       of Hours" block with worked examples for each  

    ### Version 3.4 Updates

    ✅ **Trucking cost model corrected** — trucks are now billed for all productive  
       hours on site (num trucks × hrs/day × rate × project days). Extra trucks now  
       correctly increase cost even when excavation is the bottleneck  
    ✅ **Truck utilization %** — new metric in Capacity tab and report shows what  
       fraction of contracted truck hours are actively on trips vs. idle  
    ✅ **Bottleneck tip updated** — now recommends optimal truck count when excess  
       trucks are detected  
    ✅ **Default values updated** — total volume, equipment rates, fees, and trip  
       times updated to match current project inputs  

    ### Version 3.5 Updates

    ✅ **Calendar days bug fixed** — was incorrectly showing the same value as  
       working days; now correctly accounts for weekends:  
       Calendar Days = (Complete Weeks × 7) + Remaining Days + Weather Days  
    ✅ **Example:** 162 working days at 5 days/week = 32 full weeks + 2 days  
       = 226 calendar days (not 162)  

    ### Version 3.6 Updates

    ✅ **Trucking cost corrected** — trucks operate within productive hours but are  
       paid for the full yard-to-yard day (operator paid hours). Cost now uses  
       paid hours/day, not productive hours/day  
    ✅ **Truck rate updated** — default hourly rate updated to $105/hr  
    ✅ **Miscellaneous Equipment section** — Crew Truck moved here; added  
       Porta Potty, Safety Trailer, and Dump Trailer as $/day inputs (default $0)  
    ✅ **EC&I base updated** — now includes all misc equipment, not just crew truck  

    ### Version 3.7 Updates

    ✅ **Truck utilization recommendation fixed** — previous formula was circular  
       (used current utilization % × current truck count), causing the suggestion  
       to chase itself lower with each truck removed  
    ✅ **Correct formula:** optimal trucks = CEILING(excavation CY/day ÷ (trips/truck × truck capacity))  
       — independent of how many trucks are currently entered  

    ### Version 3.8 Updates

    ✅ **Mob/Demob moved** — inputs relocated from equipment sections into Miscellaneous  
       Equipment section for cleaner organization  
    ✅ **Mob/Demob defaults** — reduced from $5,000 to $2,500 per unit  
    ✅ **Backfill default** — "Backfill Available at Landfill" now unchecked by default  
    ✅ **Backfill travel renamed** — "Travel to Backfill Site" → "Additional Travel Time  
       for Backfill" to clarify it's extra time added on top of the landfill round-trip  

    ### Version 3.9 Updates

    ✅ **Excel model export** — CSV replaced with a full Excel financial model (.xlsx)  
    ✅ **Live formulas** — every calculated value in the Excel file is a real formula;  
       change any blue input cell and all results recalculate instantly  
    ✅ **Full model structure** — inputs on the left (blue), schedule/capacity/cost/  
       environmental calculations on the right (black), with color-coded sections  
    ✅ **OT, trucking, mob/demob, fuel surcharge** all expressed as Excel formulas  
    """)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
footer_col1, footer_col2 = st.columns([3, 1])
with footer_col1:
    st.markdown("**Dig and Haul Cost Calculator** v3.9 | Built by Clean Futures with Streamlit")
with footer_col2:
    logo_path = Path("Clean_Futures_2.png")
    if logo_path.exists():
        st.image(str(logo_path), width=150)
