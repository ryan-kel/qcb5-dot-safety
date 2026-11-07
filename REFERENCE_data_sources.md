# Data Sources

This analysis relies on public datasets provided by **NYC Open Data**.

## 1. NYC 311 Service Requests from 2020 to Present
*   **Source**: NYC Open Data
*   **Agency**: NYC Office of Technology and Innovation / 311
*   **URL**: [https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9)
*   **Description**: Current NYC Open Data view `erm2-nwe9` contains 311 service requests from 2020 to present. Earlier 2010-2019 records are in a separate archived view.
    *   **Usage**: 
        1.  **Maintenance**: `agency`='DOT' + 'Traffic Signal Condition', 'Street Light Condition', 'Sign Missing'.
        2.  **Speed Camera Proxy**: Filtered for `descriptor`='Traffic Camera' (as no public "Camera Request" dataset exists).

## 2. Motor Vehicle Collisions - Crashes
*   **Source**: NYC Open Data
*   **Agency**: New York City Police Department (NYPD)
*   **URL**: [https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95)
*   **Description**: Details on crash events.
    *   **Usage**: Fetched as CB5-area bounding-box candidates with at least one injury or fatality, then filtered to the CB5 polygon. The fetch intentionally does not require `borough='QUEENS'` because some in-polygon crash rows have blank borough fields.

## 3. Traffic Signal and All-Way Stop Study Requests
*   **Source**: NYC Open Data
*   **Agency**: DOT
*   **URL**: [https://data.cityofnewyork.us/Transportation/Traffic-Signal-and-All-Way-Stop-Study-Requests/w76s-c5u4](https://data.cityofnewyork.us/Transportation/Traffic-Signal-and-All-Way-Stop-Study-Requests/w76s-c5u4)
*   **Description**: Tracks "New Infrastructure" requests (Studies).
    *   **Usage**: Primary source for Denial Rate analysis.
    *   **CB5 subset**: `output/data_cb5_signal_studies.csv` is a curated input because the source lacks coordinates and a community-board field. `output/data_cb5_signal_studies_provenance.csv` checks the curated rows against the committed raw snapshot by `id` and `referencenumber`; it does not complete the required human review of CB5 inclusion.
    *   **Logic**:
        *   **Core Traffic Control**: Filtered OUT `Accessible Pedestrian Signal` to focus on Stop Signs/Signals.
        *   **Denial Rate**: `(Study Request Denial + Engineering Study Completed)` / `Total Resolved`.

## 4. Speed Reducer Tracking System (SRTS)
*   **Source**: NYC Open Data
*   **Agency**: DOT
*   **URL**: [https://data.cityofnewyork.us/Transportation/Speed-Reducer-Tracking-System-SRTS-/9n6h-pt9g](https://data.cityofnewyork.us/Transportation/Speed-Reducer-Tracking-System-SRTS-/9n6h-pt9g)
*   **Description**: Tracks requests for speed bumps, humps, and cushions.
    *   **Key Fields**: `segmentstatusdescription` (e.g., "Not Feasible", "Feasible").
    *   **Usage**: Used to identify the high rejection rate of traffic calming measures in CB5.

## 5. Accessible Pedestrian Signal (APS) Locations
*   **Source**: NYC Open Data
*   **URL**: [https://data.cityofnewyork.us/Transportation/Accessible-Pedestrian-Signal-Locations/de3m-c5p4](https://data.cityofnewyork.us/Transportation/Accessible-Pedestrian-Signal-Locations/de3m-c5p4)
*   **Description**: Ground truth for installed APS units. Used for Chart 14 and the APS map layer; excluded from discretionary approval-rate calculations.

---

## Data Dictionary & Status Definitions

### Traffic Signal Studies
*   **Engineering Study Completed**: The technical analysis is finished. If not followed by "Approval", this implies **No Action Warranted** (Rejection).
*   **Study Request Denial**: Explicit rejection. Did not meet preliminary criteria.
*   **Signal Approval**: Study confirmed signal is warranted; installation approved.
*   **APS Ranking Completed**: Assessment for APS is done; added to priority list (does not guarantee immediate install).

### Speed Reducers (SRTS)
*   **Not Feasible**: Request evaluated and rejected (e.g., street too wide, fire route, etc.).
*   **Feasible**: Approved for installation pending funding/schedule.
