"""Global profile-tag rules; keep achievement IDs aligned with the desktop catalog."""
TARGETS = {
    'correct': [1, 10, 25, 50, 100, 250, 500, 999],
    'points': [100, 500, 1000, 2500, 5000, 10000, 25000, 99999],
    'streak': [3, 5, 10, 15, 25, 50, 99],
    'grails': [1, 5, 10, 25, 50, 100, 250],
    'rounds': [10, 50, 100, 250, 500, 1000],
    'first_try': [1, 10, 25, 50, 100, 250],
    'hard': [1, 10, 25, 50, 100, 250],
}
ACHIEVEMENT_IDS = {f'{metric}_{target}' for metric, targets in TARGETS.items() for target in targets}
ACHIEVEMENT_IDS |= {'linked_google', 'linked_discord'}
TAGS = {
    'owner': {'id': 'owner', 'name': 'Owner / Creator', 'kind': 'assigned',
              'description': "Verified owner / creator of GRAIL'D."},
    'beta_tester': {'id': 'beta_tester', 'name': 'Beta Tester', 'kind': 'assigned',
                    'description': "Awarded by the owner for helping beta test GRAIL'D."},
    'top_earner': {'id': 'top_earner', 'name': 'Top earner', 'kind': 'earned',
                   'description': 'Unlocked all 50 achievements.'},
}
