# Intent

The project is a personal wealth tracking tool.
Important part of it is tracking the assests across all accounts, tracking debts and returns, budgeting, tracking of current expences.

# General desing

The app is a classic client-server.

The app should have a dedeicated layers - data storage, backend service, and frontend.
Frontend is a web page as the first step, and later an andorid app.

## Data storage

SQlite db that stores 
* All transactions
* Current balances of accounts, including cash
* Current state of debts
* Current assents and their value
* Other data required to track wealth

## Backend

A layer that host all the logic querying data and updateing data.
All connectors - e.g. iimport from sheet, cvs, manual entry, tc - live here.

## Frontend

Several clients supported. 
1. A web page that servers differnt dashboards.
2. An android app (to be added in v2).

The web page main shows the dashboards.

The top one shows the current month expencive and income, devided by categories and types (fixed, variable, one-time)

Then the year overview.
Aditional pages give access to the list of all transactions, tools to import data, manually add transactions, etc.
Imported data gets categorised by AI.

# References

See Spec.md for detailed technical specification.

Current tool I use for this is based on the the google sheet https://docs.google.com/spreadsheets/d/1K01sJOQ_6C9qIqJRg0mOlFOSd4AhtG6-4Gr9BWTLy6M/edit?gid=2089898786#gid=2089898786 Use it to understand the data and what type of thigs are needed. Do not import anything from it yet, I will do that later manaually.
