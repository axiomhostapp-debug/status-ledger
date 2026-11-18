"""Create explicitly synthetic demo incidents in an empty ledger."""
import argparse
from ledger import Ledger


def seed(store):
    if store.status()['incidents']:
        raise ValueError('Refusing to seed a nonempty ledger')
    item = store.create('Demo DNS', 'Intermittent name resolution', 'Synthetic scenario: requests to one resolver are timing out.')
    store.transition(item['id'], 'identified', 'The demo resolver has an overloaded request queue. Traffic is being moved to the secondary resolver.', 1)
    item = store.create('Demo object storage', 'Delayed object uploads', 'Synthetic scenario: uploads are taking longer than expected.')
    store.transition(item['id'], 'identified', 'A simulated worker backlog was found.', 1)
    store.transition(item['id'], 'monitoring', 'The backlog has cleared. Watching the demo queue before closing the incident.', 2)
    store.transition(item['id'], 'resolved', 'Upload times have returned to the synthetic baseline.', 3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='demo.sqlite3')
    args = parser.parse_args()
    store = Ledger(args.db)
    try:
        seed(store)
    except ValueError as error:
        parser.exit(2, f'{error}\n')
    finally:
        store.close()
