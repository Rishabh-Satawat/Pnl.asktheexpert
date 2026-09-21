-- ==========================================================================
-- Quant Desk P&L Engine — Initial Schema Migration
-- ==========================================================================

-- 1. daily_summaries
CREATE TABLE IF NOT EXISTS public.daily_summaries (
    report_date                 DATE        PRIMARY KEY,
    total_trades_executed       INTEGER     NOT NULL DEFAULT 0,
    total_strategy_runs         INTEGER     NOT NULL DEFAULT 0,
    win_count                   INTEGER     NOT NULL DEFAULT 0,
    loss_count                  INTEGER     NOT NULL DEFAULT 0,
    total_capital_deployed_peak NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_gross_pnl             NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_transaction_cost_drag NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_net_pnl               NUMERIC(18,2) NOT NULL DEFAULT 0,
    portfolio_day_net_roi_pct   NUMERIC(10,4),
    segment_breakdown           JSONB,
    strategy_breakdown          JSONB,
    report_hash                 TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.daily_summaries IS 'One row per trading day. Primary executive KPI table for founder dashboard.';

-- 2. strategy_runs
CREATE TABLE IF NOT EXISTS public.strategy_runs (
    id                          BIGSERIAL   PRIMARY KEY,
    strategy_run_uuid           UUID        NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    report_date                 DATE        NOT NULL REFERENCES public.daily_summaries(report_date) ON DELETE CASCADE,
    strategy_name               TEXT        NOT NULL,
    deployment_status           TEXT        NOT NULL DEFAULT 'EXITED',
    multiplier_x                INTEGER     NOT NULL DEFAULT 1,
    counter_int                 INTEGER,
    capital_deployed_allocated  NUMERIC(18,2) NOT NULL DEFAULT 0,
    booked_gross_pnl            NUMERIC(18,2) NOT NULL DEFAULT 0,
    allocated_charges_total     NUMERIC(18,2) NOT NULL DEFAULT 0,
    net_pnl                     NUMERIC(18,2) NOT NULL DEFAULT 0,
    net_roi_pct                 NUMERIC(10,4),
    underlying_segment          TEXT,
    entry_timestamp_ist         TIMESTAMPTZ,
    exit_timestamp_ist          TIMESTAMPTZ,
    legs_greeks                 JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_report_date ON public.strategy_runs(report_date);
CREATE INDEX IF NOT EXISTS idx_strategy_runs_segment ON public.strategy_runs(underlying_segment);
COMMENT ON TABLE public.strategy_runs IS 'One row per Tradetron strategy card per day.';

-- 3. trade_executions
CREATE TABLE IF NOT EXISTS public.trade_executions (
    id                  BIGSERIAL   PRIMARY KEY,
    execution_uuid      UUID        NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    strategy_run_uuid   UUID        REFERENCES public.strategy_runs(strategy_run_uuid) ON DELETE SET NULL,
    report_date         DATE        NOT NULL,
    vendor_symbol       TEXT        NOT NULL,
    underlying          TEXT,
    segment             TEXT,
    exchange            TEXT,
    expiry_date         DATE,
    strike_price        NUMERIC(12,2),
    option_type         TEXT,
    side                TEXT        NOT NULL,
    lots                INTEGER     NOT NULL DEFAULT 1,
    lot_size            INTEGER     NOT NULL DEFAULT 0,
    quantity            INTEGER     NOT NULL DEFAULT 0,
    execution_price     NUMERIC(12,4) NOT NULL DEFAULT 0,
    matched_pair_id     UUID,
    extra_metadata      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_executions_report_date ON public.trade_executions(report_date);
CREATE INDEX IF NOT EXISTS idx_trade_executions_strategy_run_uuid ON public.trade_executions(strategy_run_uuid);
CREATE INDEX IF NOT EXISTS idx_trade_executions_underlying ON public.trade_executions(underlying);
COMMENT ON TABLE public.trade_executions IS 'One row per executed leg from Zerodha Kite Positions.';

-- 4. charges_breakdown
CREATE TABLE IF NOT EXISTS public.charges_breakdown (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_run_uuid     UUID        REFERENCES public.strategy_runs(strategy_run_uuid) ON DELETE CASCADE,
    report_date           DATE        NOT NULL,
    charge_source         TEXT        NOT NULL DEFAULT 'FORMULA_COMPUTED',
    brokerage             NUMERIC(12,4) NOT NULL DEFAULT 0,
    exchange_turnover_fee NUMERIC(12,4) NOT NULL DEFAULT 0,
    stt                   NUMERIC(12,4) NOT NULL DEFAULT 0,
    sebi_turnover_charges NUMERIC(12,4) NOT NULL DEFAULT 0,
    stamp_duty            NUMERIC(12,4) NOT NULL DEFAULT 0,
    gst                   NUMERIC(12,4) NOT NULL DEFAULT 0,
    ipft                  NUMERIC(12,4) NOT NULL DEFAULT 0,
    total_charges         NUMERIC(12,4) NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_charges_breakdown_report_date ON public.charges_breakdown(report_date);
CREATE INDEX IF NOT EXISTS idx_charges_breakdown_strategy_run_uuid ON public.charges_breakdown(strategy_run_uuid);
COMMENT ON TABLE public.charges_breakdown IS 'Line-item Zerodha / statutory charges per strategy run per day.';

-- 5. equity_curve
CREATE TABLE IF NOT EXISTS public.equity_curve (
    report_date             DATE        PRIMARY KEY,
    daily_net_pnl           NUMERIC(18,2) NOT NULL DEFAULT 0,
    cumulative_net_pnl      NUMERIC(18,2) NOT NULL DEFAULT 0,
    daily_net_roi_pct       NUMERIC(10,4),
    cumulative_net_roi_pct  NUMERIC(10,4),
    peak_equity             NUMERIC(18,2) NOT NULL DEFAULT 0,
    drawdown_pct            NUMERIC(10,4) NOT NULL DEFAULT 0,
    running_win_rate_30d    NUMERIC(10,4),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.equity_curve IS 'Computed daily equity curve. Rebuilt by pipeline stage 9 after each trading day.';

-- auto-update updated_at trigger
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'daily_summaries','strategy_runs','trade_executions',
        'charges_breakdown','equity_curve'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%s_updated_at ON public.%s;
             CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON public.%s
             FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();',
            tbl, tbl, tbl, tbl
        );
    END LOOP;
END$$;

-- Views
CREATE OR REPLACE VIEW public.v_monthly_summary AS
SELECT
    TO_CHAR(report_date, 'YYYY-MM')           AS month,
    COUNT(*)                                   AS trading_days,
    SUM(total_gross_pnl)                      AS gross_pnl,
    SUM(total_transaction_cost_drag)          AS total_charges,
    SUM(total_net_pnl)                        AS net_pnl,
    SUM(win_count)                            AS wins,
    SUM(loss_count)                           AS losses,
    ROUND(SUM(win_count)::NUMERIC / NULLIF(SUM(win_count) + SUM(loss_count), 0) * 100, 2) AS win_rate_pct,
    ROUND(AVG(portfolio_day_net_roi_pct), 4)  AS avg_daily_roi_pct
FROM public.daily_summaries
GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE VIEW public.v_segment_pnl AS
SELECT
    underlying_segment,
    COUNT(*)                       AS strategy_count,
    SUM(booked_gross_pnl)         AS gross_pnl,
    SUM(allocated_charges_total)  AS total_charges,
    SUM(net_pnl)                  AS net_pnl,
    ROUND(AVG(net_roi_pct), 4)    AS avg_net_roi_pct
FROM public.strategy_runs
GROUP BY 1 ORDER BY net_pnl DESC;

-- RLS
ALTER TABLE public.daily_summaries     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.strategy_runs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trade_executions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.charges_breakdown   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equity_curve        ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'authenticated_read_daily_summaries' AND tablename = 'daily_summaries') THEN
        CREATE POLICY "authenticated_read_daily_summaries" ON public.daily_summaries FOR SELECT TO authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'authenticated_read_strategy_runs' AND tablename = 'strategy_runs') THEN
        CREATE POLICY "authenticated_read_strategy_runs" ON public.strategy_runs FOR SELECT TO authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'authenticated_read_trade_executions' AND tablename = 'trade_executions') THEN
        CREATE POLICY "authenticated_read_trade_executions" ON public.trade_executions FOR SELECT TO authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'authenticated_read_charges' AND tablename = 'charges_breakdown') THEN
        CREATE POLICY "authenticated_read_charges" ON public.charges_breakdown FOR SELECT TO authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'authenticated_read_equity_curve' AND tablename = 'equity_curve') THEN
        CREATE POLICY "authenticated_read_equity_curve" ON public.equity_curve FOR SELECT TO authenticated USING (true);
    END IF;
END$$;
