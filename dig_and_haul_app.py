"""
Dig and Haul Cost Calculator - Streamlit Web App v2.9
Run with: streamlit run dig_and_haul_app_v2.9.py

Version 2.0: Updated equipment productivity defaults to medium-class raw CY/hr midpoints;
             added full plain-text report export (assumptions + results) for AI chat use
Version 2.1: Updated loading/backfill loading time defaults to 0.10 hrs (6 min);
             lowered disposal default to $25/CY and backfill to $10/CY;
             removed backfill site equipment cost (already included in per-CY price)
Version 2.2: Updated default number of trucks from 3 to 5
Version 2.3: Added backfill volume % input; backfill cost now based on % of excavated volume
             (default 100%) rather than assuming 1:1 with excavated volume
Version 2.4: Added Section 3 to text report — full methodology explanations for all key
             metrics including cycle time, capacity, bottleneck, costs, and CO2
Version 2.5: Added Recalculate button in main results area for quick re-runs without
             scrolling back to sidebar
Version 2.6: Split work hours into Paid Hours (costs) and Productive Hours (volume/capacity);
             added Max Daily Volume per Equipment Pair cap (default 750 CY) to reflect
             real-world logistics constraints; updated report methodology accordingly
Version 2.7: Fixed CO2/fuel calculations to use Productive Hours — equipment only
             burns fuel when actively working, not during yard travel/downtime
Version 2.8: Fixed logic error where truck volume/day could exceed excavation cap;
             trucks now correctly limited to excavation output when excavation is
             the bottleneck; display shows theoretical vs. effective truck capacity
Version 2.9: Trips per truck per day now floored (FLOOR) — partial trips are not
             realistic; floored value drives all calculations; raw decimal shown
             in parentheses for reference
"""

import streamlit as st
import pandas as pd
import math
import os
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Dig and Haul Cost Calculator",
    page_icon="🚜",
    layout="wide"
)

# Custom CSS
st.markdown("""
    <style>
    .big-font {
        font-size:20px !important;
        font-weight: bold;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    </style>
    """, unsafe_allow_html=True)

# Logo and Title - Centered
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    # Check if logo file exists
    logo_path = Path("Clean_Futures_2.png")
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown("<h2 style='text-align: center;'>Clean Futures</h2>", unsafe_allow_html=True)
    
    st.markdown("<h1 style='text-align: center;'>Dig and Haul Cost Calculator</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Calculate costs and CO2 emissions for excavating contaminated soil and replacing with clean backfill</p>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray; font-size: 13px;'>Version 2.9</p>", unsafe_allow_html=True)

# Sidebar for inputs
st.sidebar.header("📋 Project Inputs")

# Project Info
st.sidebar.subheader("Project Information")
total_volume = st.sidebar.number_input("Total Volume to Excavate (CY)", min_value=1, value=1000, step=50)
backfill_pct = st.sidebar.number_input("Backfill Volume (% of excavated)", min_value=0, max_value=100, value=100, step=5)
backfill_volume = total_volume * (backfill_pct / 100)
st.sidebar.caption(f"Backfill volume: {backfill_volume:,.0f} CY ({backfill_pct}% of {total_volume:,} CY)")
paid_hours_per_day = st.sidebar.number_input("Paid Hours per Day", min_value=1, value=10, step=1,
    help="Total hours paid for equipment and operators per day — used for cost calculations.")
productive_hours_per_day = st.sidebar.number_input("Productive Hours per Day", min_value=1, value=8, step=1,
    help="Hours of actual productive work per day (excludes travel to/from yard, breaks, inspections, etc.) — used for volume and capacity calculations.")
st.sidebar.caption(f"Field efficiency: {productive_hours_per_day/paid_hours_per_day*100:.0f}% of paid hours are productive")

# Equipment
st.sidebar.subheader("Equipment at Site")
st.sidebar.caption("Note: Hourly rates typically include fuel")

num_excavators = st.sidebar.number_input("Number of Excavators", min_value=0, value=1, step=1)
excavator_rate = st.sidebar.number_input("Excavator Hourly Rate ($/hr, includes fuel)", min_value=0, value=150, step=5)
excavator_fuel = st.sidebar.number_input("Excavator Fuel (gal/hr) - for CO2 tracking", min_value=0.0, value=6.0, step=0.5)
excavator_capacity = st.sidebar.number_input("Excavator Production (CY/hr)", min_value=0, value=105, step=5)

num_loaders = st.sidebar.number_input("Number of Loaders", min_value=0, value=1, step=1)
loader_rate = st.sidebar.number_input("Loader Hourly Rate ($/hr, includes fuel)", min_value=0, value=125, step=5)
loader_fuel = st.sidebar.number_input("Loader Fuel (gal/hr) - for CO2 tracking", min_value=0.0, value=5.0, step=0.5)
loader_capacity = st.sidebar.number_input("Loader Production (CY/hr)", min_value=0, value=130, step=5)

max_volume_per_pair = st.sidebar.number_input(
    "Max Daily Volume per Equipment Pair (CY)",
    min_value=0, value=750, step=50,
    help="Real-world ceiling on daily excavation volume per excavator/loader pair, accounting for logistics, inspections, operator breaks, truck queuing, etc.")
st.sidebar.caption("Based on 1 excavator + 1 loader working together. Scale with number of pairs.")

# Trucking
st.sidebar.subheader("Trucking")
num_trucks = st.sidebar.number_input("Number of Trucks", min_value=1, value=5, step=1)
truck_capacity = st.sidebar.number_input("Truck Capacity (CY)", min_value=1, value=18, step=1)
truck_hourly_rate = st.sidebar.number_input("Truck Hourly Rate ($/hr, includes driver & fuel)", min_value=0, value=85, step=5)
truck_fuel_rate = st.sidebar.number_input("Truck Fuel (gal/hr) - for CO2 tracking", min_value=0.0, value=4.0, step=0.5)

# Fuel Surcharge
st.sidebar.subheader("Fuel Surcharge (Optional)")
fuel_surcharge_enabled = st.sidebar.checkbox("Enable Fuel Surcharge", value=False)
if fuel_surcharge_enabled:
    fuel_surcharge_amount = st.sidebar.number_input("Surcharge Amount ($)", min_value=0, value=250, step=50)
    fuel_surcharge_interval = st.sidebar.selectbox("Surcharge Interval", ["daily", "weekly", "per-trip"])
else:
    fuel_surcharge_amount = 0
    fuel_surcharge_interval = "daily"

st.sidebar.subheader("Trip Times")
loading_time = st.sidebar.number_input("Loading Time (hours)", min_value=0.0, value=0.10, step=0.05)
travel_time = st.sidebar.number_input("Travel to Landfill (hours, one-way)", min_value=0.0, value=0.5, step=0.1)
landfill_time = st.sidebar.number_input("Time at Landfill (wait + dump, hours)", min_value=0.0, value=0.5, step=0.1)

# Backfill
st.sidebar.subheader("Backfill")
backfill_at_landfill = st.sidebar.checkbox("Backfill Available at Landfill", value=True)
backfill_cost = st.sidebar.number_input("Backfill Cost ($/CY)", min_value=0, value=10, step=1)

if not backfill_at_landfill:
    travel_to_backfill = st.sidebar.number_input("Travel to Backfill Site (hours)", min_value=0.0, value=0.5, step=0.1)
    backfill_loading_time = st.sidebar.number_input("Backfill Loading Time (hours)", min_value=0.0, value=0.10, step=0.05)
else:
    travel_to_backfill = 0
    backfill_loading_time = 0

# Disposal
st.sidebar.subheader("Disposal")
disposal_cost = st.sidebar.number_input("Disposal Cost ($/CY)", min_value=0, value=25, step=1)

# Calculate button
calculate = st.sidebar.button("🧮 Calculate", type="primary")

# Main content area
if calculate or 'results' in st.session_state:
    
    # Perform calculations
    # Equipment capacity - Sequential (excavator -> loader, use minimum)
    excavator_total_capacity = num_excavators * excavator_capacity
    loader_total_capacity = num_loaders * loader_capacity
    
    if excavator_total_capacity > 0 and loader_total_capacity > 0:
        excavation_capacity = min(excavator_total_capacity, loader_total_capacity)
        if excavator_total_capacity < loader_total_capacity:
            equipment_bottleneck = "Excavator"
        elif loader_total_capacity < excavator_total_capacity:
            equipment_bottleneck = "Loader"
        else:
            equipment_bottleneck = "Balanced"
        num_pairs = min(num_excavators, num_loaders)
    elif excavator_total_capacity > 0:
        excavation_capacity = excavator_total_capacity
        equipment_bottleneck = "N/A"
        num_pairs = num_excavators
    else:
        excavation_capacity = loader_total_capacity
        equipment_bottleneck = "N/A"
        num_pairs = num_loaders

    # Productive hours drive volume/capacity; paid hours drive costs
    excavation_volume_per_day_uncapped = excavation_capacity * productive_hours_per_day
    daily_volume_cap = num_pairs * max_volume_per_pair if max_volume_per_pair > 0 else excavation_volume_per_day_uncapped
    excavation_volume_per_day = min(excavation_volume_per_day_uncapped, daily_volume_cap)
    volume_cap_active = excavation_volume_per_day < excavation_volume_per_day_uncapped

    # Trip time calculation
    if backfill_at_landfill:
        trip_time = loading_time + travel_time + landfill_time + travel_time + loading_time
    else:
        trip_time = loading_time + travel_time + landfill_time + travel_to_backfill + backfill_loading_time + travel_time + loading_time

    # Trucking capacity — based on productive hours
    trips_per_truck_per_day_raw = productive_hours_per_day / trip_time
    trips_per_truck_per_day = math.floor(trips_per_truck_per_day_raw)
    total_trips_per_day_theoretical_raw = trips_per_truck_per_day_raw * num_trucks
    total_trips_per_day_theoretical = trips_per_truck_per_day * num_trucks
    truck_volume_per_day_theoretical = total_trips_per_day_theoretical * truck_capacity

    # Trucks can only haul what excavation provides — cap truck volume at excavation volume
    truck_volume_per_day = min(truck_volume_per_day_theoretical, excavation_volume_per_day)
    effective_trips_per_day = math.floor(truck_volume_per_day / truck_capacity)
    effective_trips_per_day_raw = truck_volume_per_day / truck_capacity

    # Determine bottleneck
    limiting_volume = min(excavation_volume_per_day, truck_volume_per_day_theoretical)
    if truck_volume_per_day_theoretical <= excavation_volume_per_day:
        bottleneck = "Trucking"
    else:
        bottleneck = "Excavation"

    # Project duration
    project_days = math.ceil(total_volume / limiting_volume)
    project_hours = project_days * paid_hours_per_day  # costs based on paid hours

    # Number of trips
    num_trips = math.ceil(total_volume / truck_capacity)
    
    # Costs
    # Equipment (fuel included in hourly rate)
    excavator_cost = num_excavators * excavator_rate * project_hours
    loader_cost = num_loaders * loader_rate * project_hours
    total_equipment_cost = excavator_cost + loader_cost
    
    # Trucking (fuel included in hourly rate)
    total_truck_hours = num_trips * trip_time
    trucking_cost = total_truck_hours * truck_hourly_rate
    
    # Fuel surcharge
    if fuel_surcharge_enabled:
        if fuel_surcharge_interval == "daily":
            fuel_surcharge_cost = fuel_surcharge_amount * project_days
        elif fuel_surcharge_interval == "weekly":
            project_weeks = math.ceil(project_days / 7)
            fuel_surcharge_cost = fuel_surcharge_amount * project_weeks
        elif fuel_surcharge_interval == "per-trip":
            fuel_surcharge_cost = fuel_surcharge_amount * num_trips
        else:
            fuel_surcharge_cost = 0
    else:
        fuel_surcharge_cost = 0
    
    # Disposal
    total_disposal_cost = total_volume * disposal_cost
    
    # Backfill
    total_backfill_cost = backfill_volume * backfill_cost
    
    # Total cost (NO separate fuel costs - included in hourly rates)
    total_cost = (total_equipment_cost + 
                  trucking_cost + 
                  fuel_surcharge_cost +
                  total_disposal_cost + 
                  total_backfill_cost)
    
    cost_per_cy = total_cost / total_volume
    
    # CO2 calculations (fuel tracked for emissions only, not billed)
    # Uses productive hours — equipment only burns fuel when actively working
    productive_project_hours = project_days * productive_hours_per_day
    total_fuel_gallons = (num_excavators * excavator_fuel * productive_project_hours + 
                         num_loaders * loader_fuel * productive_project_hours +
                         total_truck_hours * truck_fuel_rate)
    co2_lbs = total_fuel_gallons * 22.4  # EPA standard
    co2_tons = co2_lbs / 2000
    
    # Store results
    st.session_state['results'] = {
        'total_cost': total_cost,
        'cost_per_cy': cost_per_cy,
        'project_days': project_days,
        'project_hours': project_hours,
        'num_trips': num_trips,
        'bottleneck': bottleneck,
        'co2_tons': co2_tons,
        'excavator_capacity': excavator_total_capacity,
        'loader_capacity': loader_total_capacity,
        'excavation_capacity': excavation_capacity,
        'equipment_bottleneck': equipment_bottleneck,
        'num_pairs': num_pairs,
        'excavation_volume_per_day_uncapped': excavation_volume_per_day_uncapped,
        'daily_volume_cap': daily_volume_cap,
        'volume_cap_active': volume_cap_active,
        'excavation_volume_per_day': excavation_volume_per_day,
        'truck_volume_per_day': truck_volume_per_day,
        'truck_volume_per_day_theoretical': truck_volume_per_day_theoretical,
        'effective_trips_per_day': effective_trips_per_day,
        'effective_trips_per_day_raw': effective_trips_per_day_raw,
        'trips_per_truck_per_day': trips_per_truck_per_day,
        'trips_per_truck_per_day_raw': trips_per_truck_per_day_raw,
        'total_trips_per_day_theoretical': total_trips_per_day_theoretical,
        'total_trips_per_day_theoretical_raw': total_trips_per_day_theoretical_raw,
        'total_equipment_cost': total_equipment_cost,
        'trucking_cost': trucking_cost,
        'fuel_surcharge_cost': fuel_surcharge_cost,
        'total_disposal_cost': total_disposal_cost,
        'total_backfill_cost': total_backfill_cost,
        'total_fuel_gallons': total_fuel_gallons,
        'trip_time': trip_time,
    }
    
    results = st.session_state['results']
    
    # Recalculate button — convenience trigger near results so user doesn't have to scroll to sidebar
    recalc_col, spacer = st.columns([1, 4])
    with recalc_col:
        st.button("🔄 Recalculate", type="primary", key="recalc_btn")

    # Display results
    st.header("📊 Results Summary")
    
    # Key metrics in columns
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Cost", f"${results['total_cost']:,.0f}")
        st.metric("Cost per CY", f"${results['cost_per_cy']:.2f}")
    
    with col2:
        st.metric("Project Duration", f"{results['project_days']} days")
        st.metric("Work Hours", f"{results['project_hours']} hrs")
    
    with col3:
        st.metric("CO2 Emissions", f"{results['co2_tons']:.2f} tons")
        st.metric("Truck Trips", f"{results['num_trips']} trips")
    
    with col4:
        st.metric("Bottleneck", results['bottleneck'])
        st.metric("Equipment Limit", results['equipment_bottleneck'])
    
    # Detailed breakdowns
    st.header("📈 Detailed Analysis")
    
    tab1, tab2, tab3 = st.tabs(["💰 Cost Breakdown", "⚙️ Capacity Analysis", "🌍 Environmental Impact"])
    
    with tab1:
        st.subheader("Cost Breakdown")
        
        col1, col2 = st.columns(2)
        
        with col1:
            cost_data = {
                'Category': [
                    'Equipment (includes fuel)',
                    'Trucking (includes fuel)',
                    'Fuel Surcharge',
                    'Disposal',
                    'Backfill Material',
                ],
                'Cost': [
                    f"${results['total_equipment_cost']:,.0f}",
                    f"${results['trucking_cost']:,.0f}",
                    f"${results['fuel_surcharge_cost']:,.0f}",
                    f"${results['total_disposal_cost']:,.0f}",
                    f"${results['total_backfill_cost']:,.0f}",
                ]
            }
            df_costs = pd.DataFrame(cost_data)
            st.dataframe(df_costs, hide_index=True, use_container_width=True)
            
            st.info("💡 **Note:** Equipment and trucking hourly rates include fuel costs. Fuel consumption is tracked separately for CO2 calculations only.")
        
        with col2:
            # Bar chart of costs
            cost_values = [
                results['total_equipment_cost'],
                results['trucking_cost'],
                results['fuel_surcharge_cost'],
                results['total_disposal_cost'],
                results['total_backfill_cost'],
            ]
            cost_labels = ['Equipment', 'Trucking', 'Fuel Surcharge', 'Disposal', 'Backfill']
            
            # Create bar chart
            chart_data = pd.DataFrame({
                'Category': cost_labels,
                'Cost': cost_values
            })
            st.bar_chart(chart_data.set_index('Category'))
    
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
                    'Volume Cap Active?'
                ],
                'Value': [
                    f"{results['excavator_capacity']} CY/hr" if results['excavator_capacity'] > 0 else 'N/A',
                    f"{results['loader_capacity']} CY/hr" if results['loader_capacity'] > 0 else 'N/A',
                    f"{results['excavation_capacity']} CY/hr",
                    results['equipment_bottleneck'],
                    f"{results['num_pairs']}",
                    f"{productive_hours_per_day} hrs",
                    f"{results['excavation_volume_per_day_uncapped']:.0f} CY",
                    f"{max_volume_per_pair} CY x {results['num_pairs']} pairs = {results['daily_volume_cap']:.0f} CY",
                    f"{results['excavation_volume_per_day']:.0f} CY",
                    "⚠️ Yes — cap is limiting" if results['volume_cap_active'] else "No — theoretical rate governs"
                ]
            }
            df_capacity = pd.DataFrame(capacity_data)
            st.dataframe(df_capacity, hide_index=True, use_container_width=True)
        
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
                    'Effective Trips per Day (excavation-limited)',
                    'Effective Truck Volume per Day',
                ],
                'Value': [
                    f"{num_trucks}",
                    f"{truck_capacity} CY",
                    f"{results['trip_time']:.2f} hrs",
                    f"{productive_hours_per_day} hrs",
                    f"{results['trips_per_truck_per_day']} ({results['trips_per_truck_per_day_raw']:.2f} actual)",
                    f"{results['total_trips_per_day_theoretical']} ({results['total_trips_per_day_theoretical_raw']:.1f} actual)",
                    f"{results['truck_volume_per_day_theoretical']:.0f} CY",
                    f"{results['effective_trips_per_day']} ({results['effective_trips_per_day_raw']:.1f} actual)" if results['bottleneck'] == "Excavation" else "N/A — trucking is bottleneck",
                    f"{results['truck_volume_per_day']:.0f} CY",
                ]
            }
            df_trucks = pd.DataFrame(truck_data)
            st.dataframe(df_trucks, hide_index=True, use_container_width=True)
        
        # Bottleneck explanation
        cap_note = f"\n        - ⚠️ Daily volume cap is active: theoretical {results['excavation_volume_per_day_uncapped']:.0f} CY/day capped at {results['daily_volume_cap']:.0f} CY/day" if results['volume_cap_active'] else ""
        truck_limit_note = f"\n        - ⚠️ Truck theoretical capacity ({results['truck_volume_per_day_theoretical']:.0f} CY/day) exceeds excavation — trucks are limited to {results['truck_volume_per_day']:.0f} CY/day by excavation output" if results['bottleneck'] == 'Excavation' and results['truck_volume_per_day_theoretical'] > results['excavation_volume_per_day'] else ""
        st.info(f"""
        **System Bottleneck: {results['bottleneck']}**
        
        - Excavation can move: {results['excavation_volume_per_day']:.0f} CY/day (effective){cap_note}
        - Trucks theoretical capacity: {results['truck_volume_per_day_theoretical']:.0f} CY/day
        - Trucks effective capacity: {results['truck_volume_per_day']:.0f} CY/day{truck_limit_note}
        - Limiting factor: {min(results['excavation_volume_per_day'], results['truck_volume_per_day_theoretical']):.0f} CY/day
        - Paid hours: {paid_hours_per_day} hrs/day | Productive hours: {productive_hours_per_day} hrs/day ({productive_hours_per_day/paid_hours_per_day*100:.0f}% efficiency)
        
        {"Consider adding more trucks to increase productivity." if results['bottleneck'] == 'Trucking' else "Trucks have excess capacity. Consider reducing truck count or increasing excavation output."}
        """)
    
    with tab3:
        st.subheader("Environmental Impact")
        
        col1, col2 = st.columns(2)
        
        with col1:
            env_data = {
                'Metric': [
                    'Total Fuel Consumed',
                    'CO2 Emissions (lbs)',
                    'CO2 Emissions (tons)',
                    'CO2 per Cubic Yard'
                ],
                'Value': [
                    f"{results['total_fuel_gallons']:.0f} gallons",
                    f"{co2_lbs:,.0f} lbs",
                    f"{results['co2_tons']:.2f} tons",
                    f"{co2_lbs / total_volume:.2f} lbs/CY"
                ]
            }
            df_env = pd.DataFrame(env_data)
            st.dataframe(df_env, hide_index=True, use_container_width=True)
            
            st.caption("Note: Fuel consumption tracked for CO2 calculations. Fuel costs are included in equipment/trucking hourly rates.")
        
        with col2:
            st.metric("🌳 Equivalent Trees Needed", f"{int(results['co2_tons'] * 16.5):,}")
            st.caption("Trees needed to offset CO2 over 1 year (EPA estimate)")
            
            st.metric("🚗 Equivalent Car Miles", f"{int(results['co2_tons'] * 2500):,}")
            st.caption("Miles driven by average car (EPA estimate)")
    
    # Download results
    st.header("💾 Download Results")

    # --- Build plain-text report ---
    from datetime import date

    backfill_location_str = "At landfill (no separate trip)" if backfill_at_landfill else "Separate backfill site"
    if backfill_at_landfill:
        backfill_trip_str = "N/A (backfill at landfill)"
    else:
        backfill_trip_str = f"{travel_to_backfill:.2f} hrs one-way + {backfill_loading_time:.2f} hrs loading"

    if fuel_surcharge_enabled:
        surcharge_str = f"${fuel_surcharge_amount:,} {fuel_surcharge_interval}"
    else:
        surcharge_str = "Disabled"

    report_lines = [
        "=" * 60,
        "  DIG AND HAUL COST ESTIMATE REPORT",
        "  Clean Futures | Dig and Haul Cost Calculator v2.9",
        f"  Generated: {date.today().strftime('%B %d, %Y')}",
        "=" * 60,
        "",
        "--- SECTION 1: INPUT ASSUMPTIONS ---",
        "",
        "[ Project Parameters ]",
        f"  Total Volume to Excavate:       {total_volume:,} CY",
        f"  Paid Hours per Day:             {paid_hours_per_day} hrs  (used for cost calculations)",
        f"  Productive Hours per Day:       {productive_hours_per_day} hrs  (used for volume/capacity calculations)",
        f"  Field Efficiency:               {productive_hours_per_day/paid_hours_per_day*100:.0f}% of paid hours are productive",
        "",
        "[ Excavation Equipment ]",
        f"  Number of Excavators:           {num_excavators}",
        f"  Excavator Hourly Rate:          ${excavator_rate}/hr (fuel included)",
        f"  Excavator Fuel Consumption:     {excavator_fuel} gal/hr (CO2 tracking only)",
        f"  Excavator Production Rate:      {excavator_capacity} CY/hr each",
        f"  Total Excavator Capacity:       {results['excavator_capacity']} CY/hr",
        "",
        "[ Loader Equipment ]",
        f"  Number of Loaders:              {num_loaders}",
        f"  Loader Hourly Rate:             ${loader_rate}/hr (fuel included)",
        f"  Loader Fuel Consumption:        {loader_fuel} gal/hr (CO2 tracking only)",
        f"  Loader Production Rate:         {loader_capacity} CY/hr each",
        f"  Total Loader Capacity:          {results['loader_capacity']} CY/hr",
        "",
        "[ Equipment Productivity Constraints ]",
        f"  Equipment Pairs (Excavator+Loader): {results['num_pairs']}",
        f"  Max Daily Volume per Pair:      {max_volume_per_pair} CY",
        f"  Total Daily Volume Cap:         {results['daily_volume_cap']:.0f} CY",
        f"  Theoretical Daily Volume:       {results['excavation_volume_per_day_uncapped']:.0f} CY",
        f"  Effective Daily Volume:         {results['excavation_volume_per_day']:.0f} CY",
        f"  Volume Cap Active:              {'Yes — cap is the binding constraint' if results['volume_cap_active'] else 'No — theoretical rate governs'}",
        "",
        "[ Trucking ]",
        f"  Number of Trucks:               {num_trucks}",
        f"  Truck Capacity:                 {truck_capacity} CY",
        f"  Truck Hourly Rate:              ${truck_hourly_rate}/hr (driver & fuel included)",
        f"  Truck Fuel Consumption:         {truck_fuel_rate} gal/hr (CO2 tracking only)",
        "",
        "[ Trip Times ]",
        f"  Loading Time:                   {loading_time:.2f} hrs",
        f"  Travel to Landfill (one-way):   {travel_time:.2f} hrs",
        f"  Time at Landfill:               {landfill_time:.2f} hrs",
        f"  Full Round-Trip Cycle Time:     {results['trip_time']:.2f} hrs",
        "",
        "[ Backfill ]",
        f"  Backfill Location:              {backfill_location_str}",
        f"  Backfill Volume Factor:         {backfill_pct}% of excavated volume",
        f"  Backfill Volume:                {backfill_volume:,.0f} CY",
        f"  Backfill Cost:                  ${backfill_cost}/CY",
        f"  Backfill Site Travel/Loading:   {backfill_trip_str}",
        "",
        "[ Disposal ]",
        f"  Disposal Cost:                  ${disposal_cost}/CY",
        "",
        "[ Fuel Surcharge ]",
        f"  Fuel Surcharge:                 {surcharge_str}",
        "",
        "=" * 60,
        "--- SECTION 2: CALCULATED RESULTS ---",
        "",
        "[ Project Duration ]",
        f"  Total Project Days:             {results['project_days']} days",
        f"  Total Project Hours:            {results['project_hours']} hrs",
        f"  Total Truck Trips:              {results['num_trips']:,} trips",
        f"  Trips per Truck per Day:        {results['trips_per_truck_per_day']:.1f}",
        "",
        "[ Capacity & Bottleneck Analysis ]",
        f"  Excavation Capacity (net):      {results['excavation_capacity']} CY/hr",
        f"  Equipment Bottleneck:           {results['equipment_bottleneck']}",
        f"  Excavation Volume per Day:      {results['excavation_volume_per_day']:.0f} CY",
        f"  Truck Volume per Day:           {results['truck_volume_per_day']:.0f} CY",
        f"  System Bottleneck:              {results['bottleneck']}",
        "",
        "[ Cost Breakdown ]",
        f"  Equipment Cost:                 ${results['total_equipment_cost']:>12,.2f}",
        f"  Trucking Cost:                  ${results['trucking_cost']:>12,.2f}",
        f"  Fuel Surcharge:                 ${results['fuel_surcharge_cost']:>12,.2f}",
        f"  Disposal Cost:                  ${results['total_disposal_cost']:>12,.2f}",
        f"  Backfill Material Cost:         ${results['total_backfill_cost']:>12,.2f}",
        f"  {'─' * 38}",
        f"  TOTAL PROJECT COST:             ${results['total_cost']:>12,.2f}",
        f"  Cost per Cubic Yard:            ${results['cost_per_cy']:>12,.2f}",
        "",
        "[ Environmental Impact ]",
        f"  Total Fuel Consumed:            {results['total_fuel_gallons']:,.0f} gallons",
        f"  CO2 Emissions:                  {results['co2_tons']:.2f} tons",
        f"  Equivalent Trees to Offset:     {int(results['co2_tons'] * 16.5):,} trees (1-year)",
        f"  Equivalent Car Miles:           {int(results['co2_tons'] * 2500):,} miles",
        "",
        "=" * 60,
        "  NOTE: Equipment and trucking hourly rates include fuel.",
        "  Fuel consumption inputs are used for CO2 tracking only.",
        "=" * 60,
        "",
        "=" * 60,
        "--- SECTION 3: HOW KEY METRICS WERE DERIVED ---",
        "=" * 60,
        "",
        "[ Truck Cycle Time ]",
        "  Every truck trip follows a fixed sequence of time segments.",
        "  When backfill is available at the landfill:",
        "    Cycle Time = Loading + Travel to Landfill + Time at Landfill",
        "                 + Return Travel + Loading (for backfill return trip)",
        "  When backfill comes from a separate site, the truck makes an",
        "  additional leg: Travel to Backfill Site + Backfill Loading Time",
        "  is added into the cycle before the final return to the job site.",
        f"  This project's cycle time: {results['trip_time']:.2f} hrs per trip",
        "",
        "[ Trucking Capacity ]",
        "  How much volume trucks can move in a day is calculated as:",
        "    Trips per Truck per Day = FLOOR(Productive Hours / Cycle Time)",
        "    Partial trips are rounded DOWN — a truck can only count a trip",
        "    it can complete within productive hours.",
        "    Total Trips per Day (theoretical) = Floored Trips x Num Trucks",
        "    Truck Volume per Day (theoretical) = Trips per Day x Truck Capacity",
        "  Trucks can only haul what excavation provides. When excavation is",
        "  the bottleneck, effective truck volume is capped accordingly.",
        "    Effective Truck Volume/Day = MIN(Theoretical, Excavation Volume/Day)",
        f"  This project: FLOOR({productive_hours_per_day} hrs / {results['trip_time']:.2f} hr cycle) = "
        f"{results['trips_per_truck_per_day']} trips/truck ({results['trips_per_truck_per_day_raw']:.2f} actual) x "
        f"{num_trucks} trucks x {truck_capacity} CY = "
        f"{results['truck_volume_per_day_theoretical']:.0f} CY/day (theoretical)",
        f"  Effective: MIN({results['truck_volume_per_day_theoretical']:.0f}, "
        f"{results['excavation_volume_per_day']:.0f}) = "
        f"{results['truck_volume_per_day']:.0f} CY/day",
        "",
        "[ Excavation Equipment Capacity ]",
        "  The excavator and loader work as a sequential chain — material",
        "  moves from excavator to loader before being loaded into trucks.",
        "  The slower of the two machines limits the overall throughput.",
        "    Excavation Capacity = MIN(Excavator CY/hr, Loader CY/hr)",
        "                         x Number of each machine",
        "  If only one machine type is present, that machine's capacity",
        "  is used directly.",
        "  Theoretical daily volume = Excavation Capacity x Productive Hours",
        f"  This project: MIN({results['excavator_capacity']} CY/hr excavator, "
        f"{results['loader_capacity']} CY/hr loader) = "
        f"{results['excavation_capacity']} CY/hr x {productive_hours_per_day} productive hrs = "
        f"{results['excavation_volume_per_day_uncapped']:.0f} CY/day (theoretical)",
        f"  Equipment bottleneck: {results['equipment_bottleneck']}",
        "",
        "[ Daily Volume Cap ]",
        "  Real-world logistics prevent equipment from achieving its full",
        "  theoretical output. Factors such as operator breaks, truck",
        "  queuing, environmental consultant inspections, and site",
        "  constraints impose a practical ceiling on daily throughput.",
        "  This cap is applied per excavator/loader pair.",
        "    Daily Volume Cap = Max Volume per Pair x Number of Pairs",
        "    Effective Excavation Volume/Day = MIN(Theoretical, Cap)",
        f"  This project: {max_volume_per_pair} CY/pair x {results['num_pairs']} pairs = "
        f"{results['daily_volume_cap']:.0f} CY cap vs. "
        f"{results['excavation_volume_per_day_uncapped']:.0f} CY theoretical",
        f"  Effective: {results['excavation_volume_per_day']:.0f} CY/day "
        f"({'cap is binding' if results['volume_cap_active'] else 'theoretical rate governs'})",
        "",
        "[ System Bottleneck ]",
        "  The project can only move material as fast as its slowest",
        "  component. The system compares the effective daily excavation",
        "  volume against daily trucking capacity and uses the lower value",
        "  to determine how much volume is actually moved each day.",
        f"  Excavation can move: {results['excavation_volume_per_day']:.0f} CY/day (effective)",
        f"  Trucking can move:   {results['truck_volume_per_day']:.0f} CY/day",
        f"  Limiting factor:     {min(results['excavation_volume_per_day'], results['truck_volume_per_day']):.0f} CY/day ({results['bottleneck']})",
        "",
        "[ Project Duration ]",
        "  Total project days are calculated by dividing the total volume",
        "  to excavate by the limiting (bottleneck) daily volume, then",
        "  rounding up to the nearest whole day.",
        "  NOTE: Duration uses productive hours for volume, but costs use",
        "  PAID hours — equipment is on the clock for the full paid day.",
        "    Project Days  = CEILING(Total Volume / Limiting Volume/Day)",
        "    Project Hours = Project Days x Paid Hours per Day",
        f"  This project: CEILING({total_volume:,} CY / "
        f"{min(results['excavation_volume_per_day'], results['truck_volume_per_day']):.0f} CY/day) "
        f"= {results['project_days']} days x {paid_hours_per_day} paid hrs = "
        f"{results['project_hours']} billable hrs",
        "",
        "[ Cost Calculations ]",
        "  Equipment Cost:",
        "    Each machine type: Count x Hourly Rate x Total Project Hours",
        "    Project Hours = Project Days x Paid Hours per Day",
        "    Excavator and loader costs are summed for total equipment cost.",
        "    Fuel is already included in the hourly rate — not charged",
        "    separately.",
        f"  This project equipment cost: ${results['total_equipment_cost']:,.2f}",
        "",
        "  Trucking Cost:",
        "    Total Truck Hours = Number of Trips x Cycle Time per Trip",
        "    Trucking Cost     = Total Truck Hours x Truck Hourly Rate",
        "    Note: Number of Trips = CEILING(Total Volume / Truck Capacity)",
        "    Truck hours are based on trips actually needed to move the",
        "    material, not total project hours.",
        f"  This project: {results['num_trips']:,} trips x "
        f"{results['trip_time']:.2f} hrs x ${truck_hourly_rate}/hr "
        f"= ${results['trucking_cost']:,.2f}",
        "",
        "  Disposal Cost:",
        "    Total Volume x Disposal Cost per CY",
        f"  This project: {total_volume:,} CY x ${disposal_cost}/CY "
        f"= ${results['total_disposal_cost']:,.2f}",
        "",
        "  Backfill Cost:",
        "    Backfill Volume x Backfill Cost per CY",
        "    Backfill Volume = Total Excavated Volume x Backfill % Factor",
        "    The backfill % accounts for the fact that the refilled hole",
        "    may require less material than was removed (e.g. soil swell,",
        "    partial backfill, or engineered fill specifications).",
        f"  This project: {total_volume:,} CY x {backfill_pct}% = "
        f"{backfill_volume:,.0f} CY x ${backfill_cost}/CY "
        f"= ${results['total_backfill_cost']:,.2f}",
        "",
        "  Fuel Surcharge (if enabled):",
        "    Daily:    Surcharge Amount x Project Days",
        "    Weekly:   Surcharge Amount x CEILING(Project Days / 7)",
        "    Per-Trip: Surcharge Amount x Number of Trips",
        f"  This project surcharge: ${results['fuel_surcharge_cost']:,.2f}",
        "",
        "[ CO2 Emissions ]",
        "  Fuel consumption is tracked separately from cost (fuel is",
        "  already priced into hourly rates) and used only for emissions",
        "  calculations. Equipment only burns fuel when actively working,",
        "  so PRODUCTIVE hours are used here — not paid hours.",
        "    Productive Project Hours = Project Days x Productive Hours/Day",
        "    Total Fuel = (Excavators x Fuel Rate x Productive Project Hours)",
        "               + (Loaders x Fuel Rate x Productive Project Hours)",
        "               + (Total Truck Hours x Truck Fuel Rate)",
        "    CO2 (lbs)  = Total Fuel (gallons) x 22.4 lbs/gallon (EPA)",
        "    CO2 (tons) = CO2 (lbs) / 2,000",
        "  Tree equivalency: 1 ton CO2 offset per 16.5 trees per year (EPA)",
        "  Car mile equivalency: 1 ton CO2 per 2,500 car miles (EPA)",
        f"  This project: {project_days} days x {productive_hours_per_day} productive hrs = "
        f"{project_days * productive_hours_per_day} productive hrs",
        f"  {results['total_fuel_gallons']:,.0f} gallons x 22.4 "
        f"= {results['co2_tons'] * 2000:,.0f} lbs = {results['co2_tons']:.2f} tons CO2",
        "",
        "=" * 60,
    ]

    report_text = "\n".join(report_lines)

    # --- Create downloadable CSV ---
    results_summary = pd.DataFrame({
        'Metric': [
            'Total Volume (CY)',
            'Total Cost',
            'Cost per CY',
            'Project Duration (days)',
            'Project Hours',
            'Number of Trips',
            'Bottleneck',
            'Equipment Bottleneck',
            'Equipment Cost (includes fuel)',
            'Trucking Cost (includes fuel)',
            'Fuel Surcharge',
            'Disposal Cost',
            'Backfill Cost',
            'CO2 Emissions (tons)',
            'Total Fuel (gallons) - for reference'
        ],
        'Value': [
            total_volume,
            f"${results['total_cost']:,.2f}",
            f"${results['cost_per_cy']:.2f}",
            results['project_days'],
            results['project_hours'],
            results['num_trips'],
            results['bottleneck'],
            results['equipment_bottleneck'],
            f"${results['total_equipment_cost']:,.2f}",
            f"${results['trucking_cost']:,.2f}",
            f"${results['fuel_surcharge_cost']:,.2f}",
            f"${results['total_disposal_cost']:,.2f}",
            f"${results['total_backfill_cost']:,.2f}",
            f"{results['co2_tons']:.2f}",
            f"{results['total_fuel_gallons']:.0f}"
        ]
    })

    csv = results_summary.to_csv(index=False)

    # --- Download buttons side by side ---
    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        st.download_button(
            label="📄 Download Full Report (.txt)",
            data=report_text,
            file_name="dig_and_haul_report.txt",
            mime="text/plain",
            help="Plain-text report with all assumptions and results — paste directly into AI chat for estimating assistance"
        )
        st.caption("Includes all inputs & outputs. Ideal for pasting into AI chat prompts.")

    with dl_col2:
        st.download_button(
            label="📥 Download Results as CSV",
            data=csv,
            file_name="dig_and_haul_results.csv",
            mime="text/csv"
        )
        st.caption("Results summary table for spreadsheet use.")

else:
    # Welcome screen
    st.info("👈 Enter your project parameters in the sidebar and click **Calculate** to see results")
    
    st.markdown("""
    ### How to Use This Calculator
    
    1. **Enter project information** - total volume and work hours
    2. **Configure equipment** - excavators and loaders at the site
    3. **Set trucking parameters** - number of trucks, capacity, and trip times
    4. **Specify backfill location** - at landfill or separate site
    5. **Enter costs** - disposal and backfill pricing
    6. **Optional: Enable fuel surcharge** - if your contract includes one
    7. **Click Calculate** to see results!
    
    ### What You'll Get
    
    - **Total project cost** and cost per cubic yard
    - **Project duration** based on equipment and truck capacity
    - **Bottleneck analysis** - what's limiting your productivity
    - **CO2 emissions** tracking
    - **Detailed breakdowns** of costs and capacity
    
    ### Version 2.0 Updates
    
    ✅ **Fuel costs included in hourly rates** - no more double-charging!  
    ✅ **Optional fuel surcharge** - daily, weekly, or per-trip  
    ✅ **Fuel tracked for CO2** - environmental impact visibility  
    ✅ **Sequential equipment modeling** - excavator → loader chain  
    ✅ **Bottleneck identification** - trucking vs excavation  
    ✅ **Full plain-text report export** - assumptions + results for AI chat use  
    ✅ **Medium-class equipment defaults** - realistic CY/hr starting points  

    ### Version 2.1 Updates

    ✅ **Corrected loading time defaults** - 0.10 hrs (6 min) per truck load  
    ✅ **Updated disposal default** - $25/CY  
    ✅ **Updated backfill cost default** - $10/CY  
    ✅ **Backfill site equipment cost removed** - already built into per-CY price  

    ### Version 2.2 Updates

    ✅ **Default truck count updated** - 3 → 5 trucks  

    ### Version 2.3 Updates

    ✅ **Backfill volume % input added** - specify backfill as a % of excavated volume  
    ✅ **Backfill cost calculation corrected** - based on actual backfill CY, not excavated CY  

    ### Version 2.4 Updates

    ✅ **Methodology section added to report** - plain-language explanation of every key  
       calculation, with live numbers — for customer defense and AI agent training  

    ### Version 2.5 Updates

    ✅ **Recalculate button added** - appears in the results area so you can re-run  
       without scrolling back up to the sidebar  

    ### Version 2.6 Updates

    ✅ **Paid vs. Productive Hours** - separate inputs for billing hours (costs) and  
       field hours (volume/capacity); field efficiency % shown automatically  
    ✅ **Daily Volume Cap per Equipment Pair** - 750 CY default hard ceiling per  
       excavator/loader pair to reflect real-world logistics constraints  
    ✅ **Cap warning indicator** - Capacity Analysis tab flags when the cap is binding  
    ✅ **Methodology section updated** - both new concepts fully explained in report  

    ### Version 2.7 Updates

    ✅ **CO2/fuel calculations corrected** - now use Productive Hours, not Paid Hours;  
       equipment only burns fuel when actively working  

    ### Version 2.8 Updates

    ✅ **Truck volume logic fixed** - trucks can no longer show volume exceeding excavation  
       output; effective truck volume is capped at excavation volume when excavation  
       is the bottleneck  
    ✅ **Capacity table updated** - shows both theoretical and effective truck trips/volume  
    ✅ **Bottleneck tip updated** - advises reducing trucks when excavation is limiting  

    ### Version 2.9 Updates

    ✅ **Trips per day floored** - partial trips aren't realistic; FLOOR() applied to  
       trips per truck per day; raw decimal shown in parentheses for reference  
    """)

# Footer
st.markdown("---")
footer_col1, footer_col2 = st.columns([3, 1])
with footer_col1:
    st.markdown("**Dig and Haul Cost Calculator** v2.9 | Built by Clean Futures with Streamlit")
with footer_col2:
    logo_path = Path("Clean_Futures_2.png")
    if logo_path.exists():
        st.image(str(logo_path), width=150)
