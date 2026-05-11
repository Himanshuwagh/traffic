import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Map, Menu, X } from 'lucide-react';

const Navbar: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  const links = [
    { name: 'Explore Map', path: '/explore' },
    { name: 'City Rankings', path: '/rankings' },
    { name: 'About', path: '/about' },
  ];

  return (
    <nav className="sticky top-0 z-50 bg-brand-bg border-b border-brand-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center">
            <Link to="/" className="flex items-center gap-2 flex-shrink-0">
              <Map className="h-6 w-6 text-brand-amber" />
              <span className="text-white font-bold text-xl tracking-tight">TrafficLens</span>
            </Link>
          </div>
          <div className="hidden md:block">
            <div className="ml-10 flex items-center space-x-8">
              {links.map((link) => (
                <Link
                  key={link.name}
                  to={link.path}
                  className={`${
                    location.pathname === link.path
                      ? 'text-brand-amber font-medium'
                      : 'text-gray-300 hover:text-white'
                  } transition-colors px-3 py-2 rounded-md text-sm font-medium`}
                >
                  {link.name}
                </Link>
              ))}
              <button className="border border-brand-amber text-brand-amber hover:bg-brand-amber hover:text-brand-bg transition-colors px-4 py-2 rounded-md text-sm font-medium">
                Get API Access
              </button>
            </div>
          </div>
          <div className="-mr-2 flex md:hidden">
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="inline-flex items-center justify-center p-2 rounded-md text-gray-400 hover:text-white hover:bg-gray-800 focus:outline-none"
            >
              {isOpen ? <X className="block h-6 w-6" /> : <Menu className="block h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {isOpen && (
        <div className="md:hidden bg-brand-bg border-b border-brand-border">
          <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
            {links.map((link) => (
              <Link
                key={link.name}
                to={link.path}
                onClick={() => setIsOpen(false)}
                className={`${
                  location.pathname === link.path
                    ? 'text-brand-amber bg-gray-900'
                    : 'text-gray-300 hover:text-white hover:bg-gray-800'
                } block px-3 py-2 rounded-md text-base font-medium`}
              >
                {link.name}
              </Link>
            ))}
            <button className="w-full text-left mt-4 border border-brand-amber text-brand-amber px-3 py-2 rounded-md text-base font-medium">
              Get API Access
            </button>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
