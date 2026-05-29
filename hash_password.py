#!/usr/bin/env python3
"""
Utility per hashare password usando werkzeug, come nell'app
"""

from werkzeug.security import generate_password_hash

def main():
    print("=" * 50)
    print("Password Hash Generator")
    print("=" * 50)
    
    password = input("\nInserisci la password da hashare: ")
    
    if not password:
        print("❌ Errore: password non può essere vuota!")
        return
    
    hashed = generate_password_hash(password)
    
    print("\n" + "=" * 50)
    print("✅ Hash generato:")
    print("=" * 50)
    print(f"\nPassword originale: {password}")
    print(f"\nHash password: {hashed}")
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()
