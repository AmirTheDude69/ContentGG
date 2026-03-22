from app.services.sheets import SheetRowData, build_row_values, find_row_by_link


def test_find_row_by_link_returns_sheet_row_index() -> None:
    rows = [
        ['Mar 23', 'a', 'b', 'c', 'High', 'Easy', '<5', 'To Do', 'https://www.instagram.com/reel/A/'],
        ['Mar 24', 'a', 'b', 'c', 'Low', 'Hard', '15+', 'Done', 'https://www.instagram.com/reel/B/'],
    ]
    assert find_row_by_link(rows, 'https://www.instagram.com/reel/B/') == 3


def test_build_row_values_preserves_existing_status() -> None:
    data = SheetRowData(
        data_added='March 23- Mon',
        concept='concept',
        script='script',
        requirements='Outfit, Wallet',
        virality='High',
        feasibility='Easy',
        recording_time='<5',
        status='To Do',
        link='https://www.instagram.com/reel/X/',
    )

    values = build_row_values(data, existing_status='Filming')
    assert values[7] == 'Filming'
