import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppProvider, useApp } from './src/context/AppContext';
import DashboardScreen from './src/screens/DashboardScreen';
import ProfileScreen from './src/screens/ProfileScreen';
import RecommendationsScreen from './src/screens/RecommendationsScreen';
import PricesScreen from './src/screens/PricesScreen';
import RemindersScreen from './src/screens/RemindersScreen';
import BookingScreen from './src/screens/BookingScreen';
import NearbyLabsScreen from './src/screens/NearbyLabsScreen';
import LabMapScreen from './src/screens/LabMapScreen';
import {
  registerForPushNotifications,
  addNotificationResponseListener,
} from './src/notifications';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

const C = { primary: '#0A8F6C', inactive: '#9CA3AF', bg: '#F5F7FA' };

const headerStyle = { backgroundColor: C.bg, elevation: 0, shadowOpacity: 0 };
const headerTitleStyle = { fontWeight: '700', fontSize: 17 };

const TAB_ICONS = {
  Dashboard:   { focused: 'home',      unfocused: 'home-outline' },
  Reminders:   { focused: 'alarm',     unfocused: 'alarm-outline' },
  Labs:        { focused: 'map',       unfocused: 'map-outline' },
  Prices:      { focused: 'pricetags', unfocused: 'pricetags-outline' },
  Profile:     { focused: 'person',    unfocused: 'person-outline' },
};

function MainTabs() {
  const { unreadCount } = useApp();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused, color }) => {
          const icons = TAB_ICONS[route.name];
          return <Ionicons name={focused ? icons.focused : icons.unfocused} size={21} color={color} />;
        },
        tabBarActiveTintColor: C.primary,
        tabBarInactiveTintColor: C.inactive,
        tabBarStyle: {
          backgroundColor: '#FFF',
          borderTopWidth: 1,
          borderTopColor: '#E5E7EB',
          paddingTop: 4,
          paddingBottom: 4,
          height: 56,
        },
        tabBarLabelStyle: { fontSize: 10, fontWeight: '600' },
        headerStyle,
        headerTitleStyle,
      })}
    >
      <Tab.Screen
        name="Dashboard"
        component={DashboardScreen}
        options={{ headerShown: false }}
      />
      <Tab.Screen
        name="Reminders"
        component={RemindersScreen}
        options={{
          title: 'Reminders',
          tabBarBadge: unreadCount > 0 ? unreadCount : undefined,
          tabBarBadgeStyle: { backgroundColor: '#EF4444', fontSize: 9, minWidth: 16, height: 16 },
        }}
      />
      <Tab.Screen
        name="Labs"
        component={NearbyLabsScreen}
        options={{ title: 'Nearby Labs' }}
      />
      <Tab.Screen
        name="Prices"
        component={PricesScreen}
        options={{ title: 'Lab Prices' }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{ title: 'Profile' }}
      />
    </Tab.Navigator>
  );
}

function AppStack() {
  return (
    <Stack.Navigator screenOptions={{ headerStyle, headerTitleStyle }}>
      <Stack.Screen name="MainTabs" component={MainTabs} options={{ headerShown: false }} />
      <Stack.Screen name="Booking" component={BookingScreen} options={{ title: 'Book Appointment' }} />
      <Stack.Screen name="Recommendations" component={RecommendationsScreen} options={{ title: 'AI Recommendations' }} />
      <Stack.Screen name="NearbyLabs" component={NearbyLabsScreen} options={{ title: 'Nearby Labs' }} />
      <Stack.Screen name="LabMap" component={LabMapScreen} options={{ title: 'Lab Map' }} />
    </Stack.Navigator>
  );
}

function RootNavigator() {
  const { user } = useApp();

  useEffect(() => {
    // Request push notification permissions on app start
    registerForPushNotifications().catch(() => {});

    // Handle notification tap — navigate to Reminders
    const sub = addNotificationResponseListener((response) => {
      // Navigation handled by deep link or context
      console.log('[Push] Notification tapped:', response.notification.request.content.data);
    });

    return () => sub.remove();
  }, []);

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {!user ? (
        <Stack.Screen name="Onboarding" component={ProfileScreen} />
      ) : (
        <Stack.Screen name="Main" component={AppStack} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AppProvider>
        <NavigationContainer>
          <StatusBar style="dark" />
          <RootNavigator />
        </NavigationContainer>
      </AppProvider>
    </SafeAreaProvider>
  );
}
